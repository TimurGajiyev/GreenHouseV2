import fs from 'node:fs';
// Un-escape files written by browser_evaluate(filename), which JSON-quotes its result.
for (const p of process.argv.slice(2)) {
  let s = fs.readFileSync(p, 'utf8').trim();
  if (s.startsWith('"')) { s = JSON.parse(s); fs.writeFileSync(p, s, 'utf8'); }
  console.log(p + '  ->  ' + s.length + ' chars');
  const nums = s.split('\n').filter(l => /\d\s*kW|\$[\d,]+/.test(l)).slice(0, 12);
  nums.forEach(l => console.log('    | ' + l.trim().slice(0, 105)));
}
