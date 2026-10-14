// Renders index.html to PNG frames with headless Chrome (puppeteer).
// Usage: node capture.js <light|dark> <outdir> <fps | steps>
// `steps` writes one still per step (its settled state) instead of every frame.
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

(async () => {
  const [theme, outdir, mode] = process.argv.slice(2);
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1350, deviceScaleFactor: 1 });
  const url = `file://${path.resolve(__dirname, 'index.html')}?capture&theme=${theme}`;
  await page.goto(url, { waitUntil: 'networkidle0' });
  await page.evaluate(() => window.ready);
  const { total, settled } = await page.evaluate(() => ({ total: window.TOTAL, settled: window.SETTLED }));
  const times = mode === 'steps'
    ? settled
    : [...Array(Math.round(total * Number(mode))).keys()].map(i => i / Number(mode));
  for (let i = 0; i < times.length; i++) {
    await page.evaluate(t => window.render(t), times[i]);
    await page.screenshot({ path: path.join(outdir, `f${String(i).padStart(4, '0')}.png`) });
  }
  console.log(`${theme}: ${times.length} images`);
  await browser.close();
})();
