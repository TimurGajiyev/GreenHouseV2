import fs from 'node:fs';
const p = '.playwright/scripts/extract.mjs';
let s = fs.readFileSync(p, 'utf8');
const target = "new RegExp(NUL + 'C(\d+)' + NUL, 'g')";
if (!s.includes(target)) { console.log('NO MATCH'); process.exit(1); }
s = s.split(target).join("new RegExp(NUL + 'C([0-9]+)' + NUL, 'g')");
fs.writeFileSync(p, s);
console.log('patched');
