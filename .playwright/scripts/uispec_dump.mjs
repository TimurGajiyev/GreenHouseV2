import fs from 'node:fs';
const spec = JSON.parse(fs.readFileSync('reopt_test_data/ui-spec.json', 'utf8'));

// merge all three configs, keyed by field id; remember which configs each appears in
const merged = new Map();
for (const [cfgName, c] of Object.entries(spec.configs)) {
  for (const f of c.fields) {
    const k = f.id;
    if (!merged.has(k)) merged.set(k, { ...f, cfgs: [] });
    merged.get(k).cfgs.push(cfgName);
  }
}

const PANELS = ['top', 'site', 'utility', 'load_profile', 'financial', 'pv', 'battery', 'chp', 'prime_generator', 'generator', 'emissions'];
let out = '# REopt web tool — extracted UI field spec\n\nSource: https://reopt.nlr.gov/tool (live extraction)\n';
out += 'Configs captured: chp (grid-tied PV+Battery+CHP), prime (grid-tied PV+Battery+PrimeGen), offgrid (PV+Battery+Generator)\n\n';
out += '## Steps\n\n' + spec.configs.chp.steps.map((s) => '- ' + s).join('\n') + '\n\n';
out += '## Technology checkboxes\n\n| id | label (grid-tied) | off-grid? |\n| --- | --- | --- |\n';
const offIds = new Set(spec.configs.offgrid.techs.map((t) => t.id));
for (const t of spec.configs.chp.techs) out += `| \`${t.id}\` | ${t.label} | ${offIds.has(t.id) ? 'yes' : 'NO'} |\n`;
for (const t of spec.configs.offgrid.techs) if (!spec.configs.chp.techs.find((x) => x.id === t.id)) out += `| \`${t.id}\` | *(off-grid only)* ${t.label} | yes |\n`;

for (const p of PANELS) {
  const fs_ = [...merged.values()].filter((f) => f.panel === p);
  if (!fs_.length) continue;
  const title = fs_[0].panelTitle || p;
  out += `\n---\n\n## Panel \`${p}\` — ${title}  (${fs_.length} fields)\n\n`;
  for (const f of fs_) {
    out += `### ${f.label || '(no label)'}\n`;
    out += `- id: \`${f.id}\`\n`;
    out += `- name: \`${f.name}\`\n`;
    out += `- control: ${f.tag}/${f.type}${f.required ? ' **REQUIRED**' : ''}\n`;
    out += `- default: \`${f.value}\`\n`;
    if (f.placeholder) out += `- placeholder: ${f.placeholder}\n`;
    if (f.min || f.max || f.step) out += `- min/max/step: ${f.min} / ${f.max} / ${f.step}\n`;
    if (f.options) out += `- options: ${f.options.map((o) => `\`${o.v}\`=${o.t}`).join(' · ')}\n`;
    if (f.help) out += `- help: ${f.help}\n`;
    out += `- configs: ${f.cfgs.join(', ')}\n\n`;
  }
}
fs.writeFileSync('reopt_test_data/UI_FIELD_SPEC.md', out, 'utf8');
console.log('wrote reopt_test_data/UI_FIELD_SPEC.md  (' + out.length + ' chars, ' + merged.size + ' unique fields)');
const counts = {};
[...merged.values()].forEach((f) => { counts[f.panel] = (counts[f.panel] || 0) + 1; });
console.log(JSON.stringify(counts, null, 1));
