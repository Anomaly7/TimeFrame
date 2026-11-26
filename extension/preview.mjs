// Renders the popup with sample data (no real account), for design review. Not part of the extension package.
// Usage (from extension/): node preview.mjs <output-folder> [tag]
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { join, dirname, extname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const { chromium } = await import(pathToFileURL(join(here, '..', '..', 'openroom', 'frontend', 'node_modules', 'playwright', 'index.mjs')).href);
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' };
const srv = createServer((q, r) => {
  let body;
  try { body = readFileSync(join(here, decodeURIComponent(q.url.split('?')[0]))); } catch { r.writeHead(404); return r.end(); }
  r.writeHead(200, { 'Content-Type': types[extname(q.url.split('?')[0])] || 'text/plain' });
  r.end(body);
}).listen(4791);

const out = (process.argv[2] || '.').replace(/\/?$/, '/');
const tag = process.argv[3] || 'after';
const day = (d, h, m = 0) => { const x = new Date(); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() + d); x.setHours(h, m); return x.toISOString(); };
const busy = [
  [0, 9, 10.5, 'sam'], [0, 13, 15, 'priya'], [1, 8, 9.5, 'sam'], [1, 11, 13, 'marcus'], [2, 10, 12, 'priya'], [2, 14, 16, 'sam'],
  [3, 9, 11, 'marcus'], [3, 15, 17, 'sam'], [4, 12, 14, 'priya'], [5, 10, 12, 'sam'], [6, 13, 15, 'marcus'],
].map(([d, a, b, o]) => ({ start: day(d, Math.floor(a), (a % 1) * 60), end: day(d, Math.floor(b), (b % 1) * 60), owner: o + '@x.com', owner_name: o[0].toUpperCase() + o.slice(1) }));
const free = [[1, 15, 16], [2, 17, 18], [4, 9, 10]].map(([d, a, b]) => ({ start: day(d, a), end: day(d, b) }));
const mock = {
  '/auth/me': { email: 'sam@x.com', name: 'Sam' },
  '/groups': { groups: [{ id: 'Robo2345', name: 'Robotics team', is_admin: true, members: [{ name: 'You' }, { name: 'Priya' }, { name: 'Marcus' }], settings: null }] },
  '/billing/status': { pro: true, source: 'free_for_all' },
  '/availability/merge': { busy_times: busy, ranked_free_time: free },
};

const b = await chromium.launch({ channel: 'chrome' });
for (const [n, dark, signedIn] of [['loading', false, true], ['signed-in', false, true], ['signed-in-dark', true, true], ['signed-out', false, false]]) {
  const p = await b.newPage({ viewport: { width: 360, height: 640 }, colorScheme: dark ? 'dark' : 'light' });
  await p.addInitScript((signedIn) => {
    const data = signedIn ? { token: 't', groupId: 'Robo2345', userId: 'sam@x.com', renewedAt: Date.now() } : {};
    window.chrome = {
      storage: { local: { get: (k, cb) => cb(data), set: (o, cb) => cb && cb(), remove: (k, cb) => cb && cb() }, onChanged: { addListener() {} } },
      runtime: { sendMessage() {}, lastError: null }, tabs: { create() {} },
    };
  }, signedIn);
  await p.route('https://calender-app-mm4q.onrender.com/**', async (r) => {
    if (n === 'loading') await new Promise((res) => setTimeout(res, 4000));
    const path = new URL(r.request().url()).pathname;
    r.fulfill({ json: mock[path] || {}, headers: { 'access-control-allow-origin': '*' } });
  });
  p.on('pageerror', (e) => console.log('pageerror', e.message));
  await p.goto('http://localhost:4791/popup.html');
  await p.waitForTimeout(n === 'loading' ? 700 : 1200);
  if (signedIn && n !== 'loading') { await p.click('.cal-free.best').catch(() => {}); await p.waitForTimeout(200); }
  await p.screenshot({ path: `${out}timeframe-ext-${tag}-${n}.png`, fullPage: true });
}
await b.close();
srv.close();
console.log('done');
