import { parse } from 'node-html-parser';
import fs from 'node:fs';
const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
const pages = [['00-home',''],['01-reopt-examples','reopt/examples/'],['02-reopt-inputs','reopt/inputs/'],
['03-reopt-outputs','reopt/outputs/'],['04-reopt-methods','reopt/methods/'],['05-mpc-examples','mpc/examples/'],
['06-mpc-inputs','mpc/inputs/'],['07-mpc-outputs','mpc/outputs/'],['08-mpc-methods','mpc/methods/'],
['09-dev-concept','developer/concept/'],['10-dev-organization','developer/organization/'],
['11-dev-inputs','developer/inputs/'],['12-dev-adding-tech','developer/adding_tech/'],
['13-dev-documentation','developer/documentation/']];

const depthOf = el => { let d=0,p=el.parentNode; while(p){const t=(p.rawTagName||'').toLowerCase(); if(t==='ul'||t==='ol')d++; p=p.parentNode;} return d; };

console.log('page                    HTML li-by-depth        MD bullets-by-indent    match');
for (const [slug, rel] of pages) {
  const root = parse(await (await fetch(base+rel)).text());
  const m = root.querySelector('#documenter-page');
  const htmlProfile = {};
  m.querySelectorAll('li').forEach(li => { const d = depthOf(li); htmlProfile[d] = (htmlProfile[d]||0)+1; });

  const md = fs.readFileSync('docs/reopt-jl/'+slug+'.md','utf8');
  // strip fenced code so code comments starting with - are not counted
  const noCode = md.replace(/```[\s\S]*?```/g, '');
  const mdProfile = {};
  noCode.split('\n').forEach(l => { const mm = l.match(/^( *)- /); if (mm) { const d = mm[1].length/2 + 1; mdProfile[d]=(mdProfile[d]||0)+1; } });

  const fmt = o => Object.keys(o).sort().map(k=>'L'+k+':'+o[k]).join(' ') || '-';
  const a = fmt(htmlProfile), b = fmt(mdProfile);
  console.log(slug.padEnd(22) + a.padEnd(24) + b.padEnd(24) + (a===b ? 'OK' : '<-- DIFF'));
}
