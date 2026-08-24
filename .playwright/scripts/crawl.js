async (page) => {
  const SHOTS = 'D:/GreenHouseV2/screenshots/docs';
  const base = 'https://natlabrockies.github.io/REopt.jl/dev/';
  const pages = [
    ['00-home', ''],
    ['01-reopt-examples', 'reopt/examples/'],
    ['02-reopt-inputs', 'reopt/inputs/'],
    ['03-reopt-outputs', 'reopt/outputs/'],
    ['04-reopt-methods', 'reopt/methods/'],
    ['05-mpc-examples', 'mpc/examples/'],
    ['06-mpc-inputs', 'mpc/inputs/'],
    ['07-mpc-outputs', 'mpc/outputs/'],
    ['08-mpc-methods', 'mpc/methods/'],
    ['09-dev-concept', 'developer/concept/'],
    ['10-dev-organization', 'developer/organization/'],
    ['11-dev-inputs', 'developer/inputs/'],
    ['12-dev-adding-tech', 'developer/adding_tech/'],
    ['13-dev-documentation', 'developer/documentation/']
  ];
  const out = [];
  for (const [slug, rel] of pages) {
    try {
      await page.goto(base + rel, { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(400);
      await page.screenshot({ path: SHOTS + '/' + slug + '.png', scale: 'css' });
      const info = await page.evaluate(() => {
        const m = document.querySelector('#documenter-page') || document.querySelector('article');
        return { title: document.title, chars: m ? m.innerText.length : 0,
                 h: m ? m.querySelectorAll('h1,h2,h3,h4,h5,h6').length : 0,
                 scroll: document.documentElement.scrollHeight };
      });
      out.push(slug + ' | ' + info.title.replace(' · REopt.jl Documentation','') +
               ' | ' + info.chars + ' chars | ' + info.h + ' headings | ' + info.scroll + 'px tall');
    } catch (e) { out.push(slug + ' | ERROR: ' + String(e).slice(0, 120)); }
  }
  return out.join('\n');
}
