const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
const r = await fetch(base + 'search_index.js');
if (!r.ok) { console.log('no search_index.js (' + r.status + ')'); }
else {
  const t = await r.text();
  const locs = [...t.matchAll(/"location":"([^"]*)"/g)].map(m => m[1].split('#')[0]).filter(Boolean);
  const uniq = [...new Set(locs)].sort();
  console.log('distinct pages in search index: ' + uniq.length);
  uniq.forEach(u => console.log('  ' + u));
}
