import { parse } from 'node-html-parser';
const url = 'https://natlabrockies.github.io/REopt.jl/dev/reopt/inputs/';
const root = parse(await (await fetch(url)).text());
const m = root.querySelector('#documenter-page');

// how deep do lists actually nest, and how are they built?
let maxDepth = 0, nestedUl = 0;
const depthOf = (el) => { let d = 0, p = el.parentNode; while (p) { const t = (p.rawTagName||'').toLowerCase(); if (t === 'ul' || t === 'ol') d++; p = p.parentNode; } return d; };
m.querySelectorAll('li').forEach(li => { const d = depthOf(li); if (d > maxDepth) maxDepth = d; if (d > 1) nestedUl++; });
console.log('total li: ' + m.querySelectorAll('li').length);
console.log('li at nesting depth >1: ' + nestedUl);
console.log('max nesting depth: ' + maxDepth);
console.log('ul: ' + m.querySelectorAll('ul').length + '  ol: ' + m.querySelectorAll('ol').length);
console.log('dl: ' + m.querySelectorAll('dl').length + '  dt: ' + m.querySelectorAll('dt').length + '  dd: ' + m.querySelectorAll('dd').length);

// print a real sample of docstring list HTML
const ds = m.querySelectorAll('.docstring')[3] || m.querySelectorAll('article')[3];
const ul = ds ? ds.querySelector('ul') : null;
console.log('\n--- sample list HTML ---');
console.log(ul ? ul.outerHTML.slice(0, 1200) : 'none');
