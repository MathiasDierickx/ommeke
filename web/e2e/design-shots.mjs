// Ontwerpcontrole: schermafdrukken van de belangrijkste schermen met een nep-backend.
// Gebruik: node e2e/design-shots.mjs <uitvoermap>   (start zelf next dev op poort 3029)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const API = "http://api.e2e.test";
const PORT = "3029";
const out = path.resolve(process.argv[2] || "design-shots");
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
mkdirSync(out, { recursive: true });

const child = spawn(path.join(webRoot, "node_modules/.bin/next"), ["dev", "--webpack", "--hostname", "127.0.0.1", "--port", PORT], {
  cwd: webRoot, detached: true, stdio: "ignore",
  env: { ...process.env, NEXT_PUBLIC_API_URL: API, NEXT_PUBLIC_COGNITO_CLIENT_ID: "e2e", NEXT_PUBLIC_COGNITO_REGION: "eu-west-1", NEXT_TELEMETRY_DISABLED: "1" },
});
const url = `http://127.0.0.1:${PORT}`;
for (let i = 0; i < 180; i++) { try { if ((await fetch(url)).status < 500) break; } catch { /* wacht */ } await new Promise(r => setTimeout(r, 500)); }

const jwt = (c) => `e30.${Buffer.from(JSON.stringify(c)).toString("base64url")}.sig`;
const session = { accessToken: jwt({ sub: "u" }), idToken: jwt({ sub: "u", email: "an@example.test", name: "An" }), expiresAt: Date.now() + 864e5, email: "an@example.test", name: "An" };
const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
const points = Array.from({ length: 60 }, (_, i) => { const a = (i / 59) * Math.PI * 2; return [51.0415 + 0.008 * Math.sin(a), 3.7255 + 0.012 * Math.cos(a) - 0.012]; });
const route = { id: "r1", revision: 1, name: "Wandellus rond Sint-Pietersplein · 6 km", start: "Sint-Pietersplein, Gent", activity: "wandelen", region: "vlaanderen", climbs: [], total_km: 6.1, elevation_gain_m: 31, ready: true, download_url: "/api/routes/r1/gpx", shared: false,
  computed: { kwaliteit: { kassei_m: 252, offroad_pct: 41, populair_pct: 12 } }, constraints: { target_km: 6, waarschuwingen: [] },
  geometry: { points, elevation: points.map((_, i) => ({ km: i * 0.1, ele: 8 + 6 * Math.sin(i / 7) })), climbs: [], pois: [], start: { lat: points[0][0], lon: points[0][1], label: "Sint-Pietersplein" } } };
const conversations = [{ id: "c1", title: "Wandeling langs de Leie", preview: "6 km vanuit Gent", created_at: "2026-10-04T10:00:00Z" }];
const routes = [route, { ...route, id: "r2", name: "Racefietsrit Vlaamse Ardennen · 60 km", activity: "koersfiets", total_km: 61.2, elevation_gain_m: 640 }];
const reply = (body) => ({ status: 200, headers: { ...cors, "content-type": "application/json" }, body: JSON.stringify(body) });

const browser = await chromium.launch();
for (const vp of [{ name: "mobiel", width: 390, height: 844, mobile: true }, { name: "desktop", width: 1280, height: 800, mobile: false }]) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile, deviceScaleFactor: 2 });
  await page.addInitScript(v => localStorage.setItem("lusmaker.auth", JSON.stringify(v)), session);
  await page.route(`${API}/**`, async r => {
    const p = new URL(r.request().url()).pathname;
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204, headers: cors });
    if (p === "/api/conversations") return r.fulfill(reply({ conversations }));
    if (p === "/api/routes") return r.fulfill(reply({ routes, next_cursor: null }));
    if (p.startsWith("/api/routes/")) return r.fulfill(reply({ route }));
    return r.fulfill(reply({}));
  });
  await page.route(/tile\.openstreetmap/, r => r.abort());
  await page.goto(`${url}/?new=1`); await page.waitForSelector(".planner-title"); await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/${vp.name}-nieuw.png`, fullPage: false });
  await page.getByLabel("Startplaats").fill("Sint-Pietersplein, Gent");
  await page.getByRole("radio", { name: "Racefiets" }).check(); await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/${vp.name}-nieuw-racefiets.png`, fullPage: true });
  await page.goto(`${url}/routes/r1`); await page.waitForSelector(".route-sheet, .route-detail", { timeout: 20000 }).catch(() => {}); await page.waitForTimeout(1200);
  await page.screenshot({ path: `${out}/${vp.name}-route.png` });
  if (vp.mobile) { await page.goto(`${url}/?new=1`); await page.waitForSelector(".planner-title"); await page.getByRole("button", { name: "Open navigatie" }).click().catch(() => {}); await page.waitForTimeout(500); await page.screenshot({ path: `${out}/${vp.name}-menu.png` }); }
  await page.close();
}
await browser.close();
try { process.kill(-child.pid, "SIGTERM"); } catch { /* al gestopt */ }
console.log(`schermafdrukken in ${out}`);
