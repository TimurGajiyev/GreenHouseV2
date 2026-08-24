import { parse } from 'node-html-parser';
import fs from 'node:fs';
const root = parse(await (await fetch('https://natlabrockies.github.io/REopt.jl/dev/reopt/inputs/')).text());
const m = root.querySelector('#documenter-page');
const depthOf = el => { let d=0,p=el.parentNode; while(p){const t=(p.rawTagName||'').toLowerCase(); if(t==='ul'||t==='ol')d++; p=p.parentNode;} return d; };
const md = fs.readFileSync('docs/reopt-jl/02-reopt-inputs.md','utf8');

const missing = [];
m.querySelectorAll('li').forEach(li => {
  if (depthOf(li) !== 1) return;
  const t = li.text.trim().replace(/\s+/g,' ');
  const probe = t.slice(0, 40);
  if (probe && !md.includes(probe.slice(0, 30))) missing.push({ t: t.slice(0,90), parent: (li.parentNode.rawTagName||'').toLowerCase(), gp: (li.parentNode.parentNode?.rawTagName||'').toLowerCase() });
});
console.log('missing depth-1 li: ' + missing.length);
missing.slice(0, 12).forEach(x => console.log('  [' + x.gp + ' > ' + x.parent + '] ' + x.t));

// where do OL items live?
console.log('\nol count: ' + m.querySelectorAll('ol').length);
m.querySelectorAll('ol').forEach((ol,i) => console.log('  ol#'+i+' items=' + ol.querySelectorAll('li').length + ' parent=' + (ol.parentNode.rawTagName||'')));
