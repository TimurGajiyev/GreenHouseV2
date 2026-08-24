import { parse } from 'node-html-parser';
const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
const rels = ['','reopt/examples/','reopt/inputs/','reopt/outputs/','reopt/methods/','mpc/examples/','mpc/inputs/','mpc/outputs/','mpc/methods/','developer/concept/','developer/organization/','developer/inputs/','developer/adding_tech/','developer/documentation/'];
let total = 0;
for (const r of rels) {
  const h = await (await fetch(base + r)).text();
  const m = parse(h).querySelector('#documenter-page');
  const t = m ? m.querySelectorAll('table').length : 0;
  total += t;
  if (t) console.log((r || '(home)') + ': ' + t + ' tables');
}
console.log('total tables across site: ' + total);
