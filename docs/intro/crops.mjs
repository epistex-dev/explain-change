// node docs/intro/crops.mjs <session.html> <out-dir>
// Cuts the three real-page crops (journey, "Agent decided for you", "Outward actions") from the session page rendered from the
// bundled sample, in the navy theme, at 440 css px wide and 3x. Render the page first:
//   python3 skills/explain-change/scripts/render.py skills/explain-change/reference/examples/portal-day.session.json \
//     --out /tmp/x/session.html --theme navy --no-validate
// Needs puppeteer-core (PUPPETEER_CORE=<path to puppeteer-core.js>) and CHROMIUM=/usr/bin/chromium.
// The page's own hint lines are hidden: they carry the sample caveats ("not compared with a session"), which must not appear in a frame.
import path from 'node:path';
const [file, out] = process.argv.slice(2);
const {default: puppeteer} = await import(process.env.PUPPETEER_CORE);
const b = await puppeteer.launch({executablePath: process.env.CHROMIUM || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
const p = await b.newPage(); await p.setViewport({width: 440, height: 900, deviceScaleFactor: 3});
await p.goto('file://' + path.resolve(file)); await new Promise(r => setTimeout(r, 800));
await p.addStyleTag({content: '.ov .hint{display:none!important}'});
// journey: the element itself (it carries its own 16 px padding). decided / outward: the section plus 12 css px of the side panel's
// own padding on every side, so no text sits against the crop edge (the section alone has none).
const PAD = 12;
for (const [sel, name, pad] of [['#journey', 'journey', 0], ['#sec-dec', 'decided', PAD], ['#sec-out', 'outward', PAD]]) {
  const el = await p.$(sel);
  if (!pad) { await el.screenshot({path: path.join(out, `navy-${name}.png`)}); continue; }
  const r = await p.evaluate(e => { const b = e.getBoundingClientRect(), a = document.querySelector('#panel').getBoundingClientRect(); return {x: a.x + 8, y: b.y + scrollY, w: a.width - 16, h: b.height}; }, el);
  await p.screenshot({path: path.join(out, `navy-${name}.png`), clip: {x: r.x, y: r.y - pad, width: r.w, height: r.h + 2 * pad}});
}
await b.close();
