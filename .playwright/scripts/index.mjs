import fs from 'node:fs';
const dir = 'docs/reopt-jl';
const files = fs.readdirSync(dir).filter(f => f.endsWith('.md') && f !== 'INDEX.md').sort();
let out = '# REopt.jl Documentation — offline capture\n\nCaptured 2026-08-23 from https://natlabrockies.github.io/REopt.jl/dev/\nScreenshots of each page are in `../../screenshots/docs/`.\n\n| # | Page | File | Size | Headings |\n| --- | --- | --- | --- | --- |\n';
let total = 0;
for (const f of files) {
  const s = fs.readFileSync(dir + '/' + f, 'utf8');
  total += s.length;
  const title = s.split('\n')[0].replace(/^# /, '');
  const heads = (s.match(/^#{2,6} /gm) || []).length;
  const n = f.slice(0, 2);
  out += `| ${n} | ${title} | [${f}](${f}) | ${(s.length/1024).toFixed(1)} KB | ${heads} |\n`;
}
out += `\n**Total:** ${files.length} pages, ${(total/1024).toFixed(0)} KB of text.\n\n`;
out += '## Section map\n\n- `00` — Home / installation\n- `01`–`04` — REopt core: examples, inputs, outputs, methods\n- `05`–`08` — Model Predictive Control (MPC): examples, inputs, outputs, methods\n- `09`–`13` — Developer: design concepts, file organization, REoptInputs struct, adding a technology, documenting\n';
fs.writeFileSync(dir + '/INDEX.md', out, 'utf8');
console.log(out);
