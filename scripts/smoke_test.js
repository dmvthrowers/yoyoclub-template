#!/usr/bin/env node
// Click through every page of the built showcase in a real browser.
//
//   python3 scripts/build_showcase.py && node scripts/smoke_test.js
//
// For each site in _site (the showcase page and every example under _site/examples/), it opens the home page at
// phone width, follows every internal link to every other page, and fails if any page has: a failed or 4xx/5xx
// request to this site, a console error or uncaught error, sideways scrolling, or a phone menu that doesn't
// open and close. Nothing leaves your machine: outside requests are blocked. Needs Node and Playwright with Chromium
// (set CHROMIUM_PATH to use a browser you already have). Used only by the original template repository.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..', '_site'));
const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.xml': 'text/xml',
  '.txt': 'text/plain', '.webmanifest': 'application/manifest+json', '.ico': 'image/x-icon', '.ics': 'text/calendar' };

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file = path.join(root, p);
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  if (!fs.existsSync(file)) { res.writeHead(404, { 'Content-Type': 'text/html' }).end('<h1>not found</h1>'); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});

function sites() {
  const out = [];
  if (fs.existsSync(path.join(root, 'index.html'))) out.push('/');
  const ex = path.join(root, 'examples');
  if (fs.existsSync(ex)) for (const d of fs.readdirSync(ex).sort()) {
    if (fs.existsSync(path.join(ex, d, 'index.html'))) out.push(`/examples/${d}/`);
  }
  return out;
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const problems = [];
  let pages = 0;
  for (const base of sites()) {
    const queue = [base], seen = new Set();
    while (queue.length) {
      const url = queue.shift();
      if (seen.has(url)) continue;
      seen.add(url);
      const ctx = await browser.newContext({ viewport: { width: 360, height: 780 } });
      const page = await ctx.newPage();
      const where = (m) => problems.push(`${url}: ${m}`);
      await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort());
      page.on('response', r => { if (r.url().startsWith(origin) && r.status() >= 400) where(`${r.status()} for ${r.url().replace(origin, '')}`); });
      page.on('pageerror', e => where(`uncaught error: ${e.message}`));
      page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) where(`console error: ${m.text()}`); });
      await page.goto(origin + url, { waitUntil: 'load' });
      pages++;
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      if (width > 361) where(`scrolls sideways (${width}px wide at 360px)`);
      const toggle = page.locator('.nav-toggle');
      if (await toggle.count()) {
        await toggle.click();
        if ((await toggle.getAttribute('aria-expanded')) !== 'true') where('the phone menu did not open');
        await page.keyboard.press('Escape');
        if ((await toggle.getAttribute('aria-expanded')) !== 'false') where('Escape did not close the phone menu');
      }
      const links = await page.$$eval('a[href]', as => as.map(a => a.getAttribute('href')));
      for (const href of links) {
        if (!href || href.startsWith('#') || /^(mailto:|tel:|https?:|webcal:|javascript:)/.test(href)) continue;
        const next = new URL(href, origin + url);
        if (next.origin !== origin || !next.pathname.startsWith(base) || !/(\/|\.html)$/.test(next.pathname)) continue;
        queue.push(next.pathname);
      }
      await ctx.close();
    }
  }
  await browser.close();
  server.close();
  if (problems.length) {
    console.log([...new Set(problems)].map(p => '  - ' + p).join('\n'));
    console.log(`\nFAILED: ${new Set(problems).size} problem(s) across ${pages} pages.`);
    process.exit(1);
  }
  console.log(`OK: ${pages} pages clicked through, no problems found.`);
})().catch(e => { console.error(e); process.exit(2); });
