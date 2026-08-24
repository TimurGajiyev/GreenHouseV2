import { parse } from 'node-html-parser';
import fs from 'node:fs';

const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
const pages = [
  ['00-home',''],['01-reopt-examples','reopt/examples/'],['02-reopt-inputs','reopt/inputs/'],
  ['03-reopt-outputs','reopt/outputs/'],['04-reopt-methods','reopt/methods/'],['05-mpc-examples','mpc/examples/'],
  ['06-mpc-inputs','mpc/inputs/'],['07-mpc-outputs','mpc/outputs/'],['08-mpc-methods','mpc/methods/'],
  ['09-dev-concept','developer/concept/'],['10-dev-organization','developer/organization/'],
  ['11-dev-inputs','developer/inputs/'],['12-dev-adding-tech','developer/adding_tech/'],
  ['13-dev-documentation','developer/documentation/']
];

const BLOCK = new Set(['p','div','section','article','h1','h2','h3','h4','h5','h6','pre','table','tr','blockquote','header','footer','aside','dl','dt','dd','details','summary']);
const FENCE = '```';
const MK = '@@@';

const decode = s => s.replace(/&quot;/g,'"').replace(/&#39;/g,"'")
  .replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&nbsp;/g,' ').replace(/&hellip;/g,'…')
  .replace(/&mdash;/g,'—').replace(/&ndash;/g,'–').replace(/&times;/g,'×')
  .replace(/&#([0-9]+);/g,(_,d)=>String.fromCharCode(+d)).replace(/&amp;/g,'&');

// Documenter turns  a_b ... c_d  into  a<em>b ... c</em>d , destroying underscores.
// Mapping <em> back to "_" restores the identifier AND is correct markdown for real emphasis.
const inlineText = s => s
  .replace(/<\/?em>/gi, '_').replace(/<\/?i>/gi, '_')
  .replace(/<\/?strong>/gi, '**').replace(/<\/?b>/gi, '**')
  .replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');

const stripTags = s => s.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');

let CODE = [], DEPTH = 0, RECOVERED = 0;

function pushCode(lang, body) {
  CODE.push('\n\n' + FENCE + lang + '\n' + body + '\n' + FENCE + '\n');
  return MK + 'C' + (CODE.length - 1) + MK;
}

function render(node, out) {
  if (node.nodeType === 3) { out.push(node.rawText.replace(/\s+/g, ' ')); return; }
  if (node.nodeType !== 1) return;
  const tag = node.rawTagName ? node.rawTagName.toLowerCase() : '';
  const cls = node.getAttribute ? (node.getAttribute('class') || '') : '';
  if (tag === 'script' || tag === 'style') return;
  if (/docs-sourcelink|docs-heading-anchor-permalink/.test(cls)) return;

  if (/^h[1-6]$/.test(tag)) {
    out.push('\n\n' + '#'.repeat(+tag[1]) + ' ' + decode(inlineText(node.innerHTML)).trim().replace(/\s+/g,' ') + '\n');
    return;
  }
  if (tag === 'pre') {
    const raw = node.innerHTML || '';
    const m = raw.match(/class="[^"]*language-([a-z0-9]+)/i);
    out.push(pushCode(m ? m[1] : '', decode(stripTags(raw)).replace(/^\n+/,'').replace(/\s+$/,'')));
    return;
  }
  // Upstream-malformed code block: a <p> that literally begins with a fence.
  if (tag === 'p') {
    const plain = decode(inlineText(node.innerHTML || '')).trim();
    if (plain.startsWith(FENCE)) {
      const lm = plain.match(/^```([a-z0-9]*)/i);
      let t = plain.slice(lm[0].length).replace(/```\s*$/, '');
      // newlines were flattened to runs of spaces; restore them
      const lines = t.split(/ {2,}/).map(s => s.trim()).filter(Boolean);
      RECOVERED++;
      out.push(pushCode(lm[1] || 'julia', lines.join('\n')));
      return;
    }
  }
  if (tag === 'em' || tag === 'i') { out.push('_'); for (const c of node.childNodes) render(c, out); out.push('_'); return; }
  if (tag === 'strong' || tag === 'b') { out.push('**'); for (const c of node.childNodes) render(c, out); out.push('**'); return; }
  if (tag === 'code' && (!node.parentNode || (node.parentNode.rawTagName || '').toLowerCase() !== 'pre')) {
    out.push('`' + decode(inlineText(node.innerHTML || '')).trim() + '`'); return;
  }
  if (tag === 'ul' || tag === 'ol') {
    DEPTH++; out.push('\n');
    for (const c of node.childNodes) render(c, out);
    DEPTH--; out.push('\n'); return;
  }
  if (tag === 'li') {
    out.push('\n' + MK + 'I' + Math.max(0, DEPTH - 1) + MK + '- ');
    for (const c of node.childNodes) render(c, out);
    return;
  }
  if (BLOCK.has(tag)) out.push('\n');
  for (const c of node.childNodes) render(c, out);
  if (BLOCK.has(tag)) out.push('\n');
}

const report = [];
let totalRecovered = 0;
for (const [slug, rel] of pages) {
  const url = base + rel;
  const root = parse(await (await fetch(url)).text());
  const main = root.querySelector('#documenter-page') || root.querySelector('article');
  if (!main) { report.push(slug + ' | NO MAIN'); continue; }
  CODE = []; DEPTH = 0; RECOVERED = 0;
  const out = [];
  render(main, out);

  let body = decode(out.join(''))
    .replace(/[ \t]+/g,' ').replace(/ *\n */g,'\n').replace(/\n{3,}/g,'\n\n')
    .replace(/(^|\n)(@@@I[0-9]+@@@)?- *\n+/g,'$1$2- ')
    .trim();

  const isBullet = l => /^(@@@I[0-9]+@@@)?- /.test(l);
  const lines = body.split('\n'), kept = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === '' && isBullet(lines[i-1]||'') && isBullet(lines[i+1]||'')) continue;
    kept.push(lines[i]);
  }
  body = kept.join('\n')
    .replace(/@@@I([0-9]+)@@@/g, (_, d) => '  '.repeat(+d))
    .replace(new RegExp(MK + 'C([0-9]+)' + MK, 'g'), (_, i) => CODE[+i]);

  const title = (root.querySelector('title')?.text || slug).replace(' · REopt.jl Documentation','');
  const md = '# ' + title + '\n\nSource: ' + url + '\n\n---\n\n' + body + '\n';
  fs.writeFileSync('docs/reopt-jl/' + slug + '.md', md, 'utf8');
  totalRecovered += RECOVERED;

  const fences = (md.match(/^```/gm) || []).length;
  const bal = fences % 2 === 0 ? 'OK  ' : 'ODD!';
  const nested = (md.match(/^ +- /gm) || []).length;
  const docs = (md.match(/— (Method|Type|Function|Macro|Constant)/g) || []).length;
  const leftover = (md.match(/<[a-z][^>]*>/gi) || []).length;
  report.push(slug.padEnd(22) + String(md.length).padStart(7) + '  fences ' + String(fences).padStart(3) + ' ' + bal +
    '  ' + String(docs).padStart(2) + ' docstrings  ' + String(nested).padStart(3) + ' nested' +
    (RECOVERED ? '  recovered ' + RECOVERED + ' broken block(s)' : '') +
    (leftover ? '  !! ' + leftover + ' tags' : ''));
}
console.log(report.join('\n'));
console.log('\ntotal upstream-broken code blocks recovered: ' + totalRecovered);
