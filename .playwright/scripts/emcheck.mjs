import { parse } from 'node-html-parser';
const root = parse(await (await fetch('https://natlabrockies.github.io/REopt.jl/dev/reopt/inputs/')).text());
const m = root.querySelector('#documenter-page');
console.log('em: ' + m.querySelectorAll('em').length + '  strong: ' + m.querySelectorAll('strong').length);
// find the node containing the literal fence text
const hits = [];
m.querySelectorAll('*').forEach(e => {
  if (e.childNodes.some(c => c.nodeType === 3 && c.rawText.includes('```'))) hits.push(e);
});
console.log('elements with literal ``` in a direct text child: ' + hits.length);
if (hits.length) {
  const h = hits[0];
  console.log('tag=' + h.rawTagName + ' class=' + (h.getAttribute('class')||''));
  console.log('--- outerHTML head ---');
  console.log(h.outerHTML.slice(0, 700));
  console.log('--- has newlines in text? ' + /\n/.test(h.text));
}
