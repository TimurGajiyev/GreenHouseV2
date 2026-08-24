import { parse } from 'node-html-parser';
import fs from 'node:fs';
const root = parse(await (await fetch('https://natlabrockies.github.io/REopt.jl/dev/reopt/inputs/')).text());
const m = root.querySelector('#documenter-page');
const depthOf = el => { let d=0,p=el.parentNode; while(p){const t=(p.rawTagName||'').toLowerCase(); if(t==='ul'||t==='ol')d++; p=p.parentNode;} return d; };
const norm = s => s.replace(/[`*_]/g,'').replace(/\s+/g,' ').trim().toLowerCase();
const md = norm(fs.readFileSync('docs/reopt-jl/02-reopt-inputs.md','utf8'));
const missing = [];
m.querySelectorAll('li').forEach(li => {
  if (depthOf(li) !== 1) return;
  const t = norm(li.text);
  if (t.length < 6) { missing.push('(EMPTY li) ' + t); return; }
  if (!md.includes(t.slice(0, 45))) missing.push(t.slice(0, 95));
});
console.log('genuinely missing depth-1 li: ' + missing.length);
missing.forEach(x => console.log('  - ' + x));
