import fs from 'node:fs';
const p = 'reopt_test_data/ui-spec.json';
let s = fs.readFileSync(p, 'utf8').trim();
if (s.startsWith('"')) s = JSON.parse(s);
const spec = JSON.parse(s);
fs.writeFileSync(p, JSON.stringify(spec, null, 1));

const cfg = process.argv[2] || 'chp';
const c = spec.configs[cfg];
console.log('config=' + cfg + '  fields=' + c.fields.length);
console.log('STEPS: ' + JSON.stringify(c.steps, null, 1));
console.log('\nTECHS:');
c.techs.forEach(t => console.log('   ' + t.id.padEnd(30) + ' "' + t.label + '"'));

// group by panel
const byPanel = {};
c.fields.forEach(f => { (byPanel[f.panel] = byPanel[f.panel] || []).push(f); });
console.log('\nPANELS:');
Object.entries(byPanel).forEach(([k, v]) =>
  console.log('   ' + k.padEnd(20) + ' n=' + String(v.length).padStart(3) + '  "' + (v[0].panelTitle || '') + '"'));
