// Volledig offline browserregressie voor de hoofdflows (issue #9).
//
// Start zelf `next dev` met een nep-API-host en onderschept elke netwerkcall
// met page.route: er gaat niets naar het internet. Alles buiten localhost en de
// nep-hosts wordt geblokkeerd. Draait elke test op 390 px (mobiel) en 1280 px
// (desktop).
//
//   npm run test:e2e                 # start zelf een dev-server
//   E2E_BASE_URL=http://127.0.0.1:3017 npm run test:e2e   # hergebruik een server
//   E2E_ONLY=409 npm run test:e2e    # filter op testnaam
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "playwright";

const API = "http://api.e2e.test";
const COGNITO = "https://cognito-idp.eu-west-1.amazonaws.com";
const PORT = process.env.E2E_PORT || "3027";
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TIMEOUT = 20_000;
const VIEWPORTS = [
  { name: "mobiel-390", width: 390, height: 844, mobile: true },
  { name: "desktop-1280", width: 1280, height: 800, mobile: false },
];

// --- Dev-server ---------------------------------------------------------

async function startServer() {
  if (process.env.E2E_BASE_URL) return { url: process.env.E2E_BASE_URL.replace(/\/+$/, ""), stop() {} };
  const url = `http://127.0.0.1:${PORT}`;
  const child = spawn(path.join(webRoot, "node_modules/.bin/next"), ["dev", "--webpack", "--hostname", "127.0.0.1", "--port", PORT], {
    cwd: webRoot,
    env: {
      ...process.env,
      NEXT_PUBLIC_API_URL: API,
      NEXT_PUBLIC_COGNITO_CLIENT_ID: "e2e-client",
      NEXT_PUBLIC_COGNITO_REGION: "eu-west-1",
      NEXT_TELEMETRY_DISABLED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
    detached: true, // eigen procesgroep, zodat stop() ook next-server opruimt
  });
  const kill = () => { try { process.kill(-child.pid, "SIGTERM"); } catch { /* al gestopt */ } };
  let output = "";
  child.stdout.on("data", (d) => { output += d; });
  child.stderr.on("data", (d) => { output += d; });
  const deadline = Date.now() + 90_000;
  for (;;) {
    if (child.exitCode !== null) throw new Error(`next dev stopte voortijdig:\n${output}`);
    try { if ((await fetch(`${url}/`)).status < 500) break; } catch { /* nog niet klaar */ }
    if (Date.now() > deadline) { kill(); throw new Error(`next dev startte niet binnen 90 s:\n${output}`); }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return { url, stop: kill };
}

// --- Nep-backend --------------------------------------------------------

const jwt = (claims) => `e30.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.sig`;
const SESSION = {
  accessToken: jwt({ sub: "e2e-user" }),
  idToken: jwt({ sub: "e2e-user", email: "fiets@example.test", name: "Test Fietser" }),
  expiresAt: Date.now() + 24 * 3600 * 1000,
  email: "fiets@example.test",
  name: "Test Fietser",
};
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization,content-type,accept,x-amz-target,x-amz-user-agent",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "access-control-expose-headers": "retry-after",
};
const json = (status, body, headers = {}) => ({ status, headers: { ...CORS, "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
const sse = (events) => ({
  status: 200,
  headers: { ...CORS, "content-type": "text/event-stream" },
  body: events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(""),
});
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const baseRoute = () => ({
  id: "r1", revision: 1, name: "Berendries-lus", created: "2026-10-02", start: "Wetteren", activity: "fietsen",
  region: "vlaanderen", climbs: ["berendries"], total_km: 30, elevation_gain_m: 240, ready: true,
  download_url: "/api/routes/r1/gpx", shared: false, geometry: null,
});

/**
 * Installeert de nep-backend op een pagina. `handlers` overschrijft per
 * "METHOD /pad" het standaardgedrag; een handler krijgt {request, body, state}.
 */
async function installBackend(page, { handlers = {}, session = true } = {}) {
  const state = { route: baseRoute(), calls: [], unexpected: [], pageErrors: [], sharedNow: false };
  page.on("pageerror", (error) => state.pageErrors.push(error.message));
  page._e2e = state;
  // Eerst de vangnet-route: alles wat niet naar localhost of een nep-host gaat wordt geblokkeerd.
  await page.route("**/*", (route) => {
    const { hostname } = new URL(route.request().url());
    if (hostname === "127.0.0.1" || hostname === "localhost") return route.continue();
    state.unexpected.push(`GEBLOKKEERD ${route.request().method()} ${route.request().url()}`);
    return route.abort();
  });
  await page.route(`${API}/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    let body = null;
    try { body = request.postDataJSON(); } catch { /* geen JSON-body */ }
    state.calls.push({ key, body });
    const handler = handlers[key] ?? defaultHandlers[key];
    if (!handler) { state.unexpected.push(`ONBEKEND ${key}`); return route.fulfill(json(404, { error: "onbekend" })); }
    return route.fulfill(await handler({ request, body, state }));
  });
  await page.route(`${COGNITO}/**`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const handler = handlers["COGNITO"];
    if (!handler) { state.unexpected.push("ONBEKEND COGNITO"); return route.fulfill(json(400, { __type: "InternalErrorException" })); }
    state.calls.push({ key: "COGNITO", body: route.request().postDataJSON() });
    return route.fulfill(await handler({ request: route.request(), state }));
  });
  if (session) {
    await page.addInitScript((value) => { try { localStorage.setItem("lusmaker.auth", JSON.stringify(value)); } catch { /* */ } }, SESSION);
  }
  return state;
}

const defaultHandlers = {
  "GET /api/conversations": () => json(200, { conversations: [] }),
  "GET /api/routes": ({ state }) => json(200, { routes: [state.route], next_cursor: null }),
  "GET /api/routes/r1": ({ state }) => json(200, { route: state.route }),
  "POST /api/routes/r1/adjust": ({ body, state }) => {
    state.route = { ...state.route, total_km: body.target_km ?? state.route.total_km, revision: state.route.revision + 1 };
    return json(200, { route: state.route });
  },
  "POST /api/routes/r1/share": ({ state }) => { state.route = { ...state.route, shared: true }; return json(200, { token: "tok123", url: "http://share.e2e.test/s/tok123" }); },
  "DELETE /api/routes/r1/share": ({ state }) => { state.route = { ...state.route, shared: false }; return json(204, {}); },
  "GET /api/routes/r1/gpx": () => ({ status: 200, headers: { ...CORS, "content-type": "application/gpx+xml" }, body: '<?xml version="1.0"?><gpx version="1.1"/>' }),
  "GET /api/routes/r1/fit": () => ({ status: 200, headers: { ...CORS, "content-type": "application/octet-stream" }, body: "FIT-bytes" }),
};

// --- Toegankelijkheidshulpen ---------------------------------------------

/** Alle zichtbare bedienbare elementen die geen toegankelijke naam hebben. */
async function unnamedControls(page) {
  return page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
    const name = (el) => {
      const labelled = el.getAttribute("aria-labelledby");
      if (labelled) return labelled.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ").trim();
      return (el.getAttribute("aria-label") || (el.labels && [...el.labels].map((l) => l.textContent).join(" ")) || el.textContent || el.getAttribute("title") || "").trim();
    };
    return [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, summary")]
      .filter(visible).filter((el) => !name(el)).map((el) => el.outerHTML.slice(0, 120));
  });
}

/** Tab door de pagina en geef per focusstop {name, visible-focus} terug. */
async function tabStops(page, max = 60) {
  const stops = [];
  // Zet het sequentiële focuspunt terug naar het begin van het document.
  await page.evaluate(() => { document.activeElement?.blur?.(); getSelection()?.removeAllRanges(); document.body.tabIndex = -1; document.body.focus(); document.body.removeAttribute("tabindex"); window.scrollTo(0, 0); });
  const seen = new Set();
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    // Laat CSS-overgangen (outline) eerst uitlopen voor we de stijl lezen.
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      if (el.tagName.toLowerCase() === "nextjs-portal") return { id: "dev-overlay", skip: true };
      const s = getComputedStyle(el);
      const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
      const shadow = s.boxShadow && s.boxShadow !== "none";
      const container = el.closest("label, .composer, .distance-form, .avoid-place, .auth-field, .library-filters, .adjust-row, form");
      const cs = container ? getComputedStyle(container) : null;
      const outerFocus = container ? container.matches(":focus-within") && cs.boxShadow !== "none" : false;
      const r = el.getBoundingClientRect();
      const label = (el.getAttribute("aria-label") || (el.labels && el.labels[0]?.textContent) || el.textContent || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 60);
      const onScreen = r.width > 0 && r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.top < innerHeight;
      el.dataset.e2eStop = el.dataset.e2eStop || String(Math.random());
      return { id: el.dataset.e2eStop, name: label, tag: el.tagName.toLowerCase(), focusVisible: outline || shadow || outerFocus, onScreen };
    });
    if (info?.skip) continue;
    if (!info || seen.has(info.id)) break;
    seen.add(info.id);
    stops.push(info);
  }
  return stops;
}

/** Echte meldingen; de Next.js-routeannouncer heeft ook role=alert. */
const alerts = (page) => page.locator("[role=alert]:not(#__next-route-announcer__)");

const expectNoStrays = (state, label) => {
  assert.deepEqual(state.unexpected, [], `${label}: onverwachte of geblokkeerde netwerkcalls`);
  assert.deepEqual(state.pageErrors, [], `${label}: JavaScript-fouten in de pagina`);
};

async function openRoute(page, url) {
  await page.goto(`${url}/routes/r1/`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { level: 2, name: "Berendries-lus" }).waitFor();
}

async function openHome(page, url) {
  await page.goto(`${url}/?new=1`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Een lus vanaf hier" }).waitFor();
}

/** Sluit de menubalk als hij openstaat (mobiel), zodat de rest bereikbaar is. */
async function keyboardReach(page, wanted, vp) {
  const stops = await tabStops(page);
  const names = stops.map((s) => s.name);
  for (const target of wanted) {
    assert.ok(names.some((n) => n.includes(target)), `[${vp.name}] "${target}" niet bereikbaar met Tab. Stops: ${names.join(" | ")}`);
  }
  const noFocus = stops.filter((s) => s.onScreen && !s.focusVisible).map((s) => `${s.tag}:${s.name}`);
  assert.deepEqual(noFocus, [], `[${vp.name}] focusstops zonder zichtbare focusindicator (${JSON.stringify(stops.slice(-3))})`);
  const offscreen = stops.filter((s) => !s.onScreen).map((s) => `${s.tag}:${s.name}`);
  assert.deepEqual(offscreen, [], `[${vp.name}] focus belandt buiten beeld (verborgen paneel nog tabbaar)`);
  return stops;
}

// --- Tests ----------------------------------------------------------------

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test("loginfout toont een gemelde foutmelding en labels", async ({ page, url, vp }) => {
  const state = await installBackend(page, {
    session: false,
    handlers: {
      COGNITO: async () => { await wait(300); return json(400, { __type: "NotAuthorizedException", message: "Incorrect username or password." }); },
    },
  });
  await page.goto(`${url}/`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("E-mailadres").fill("fiets@example.test");
  await page.locator("input[type=password]").fill("fout-wachtwoord-1!");
  assert.deepEqual(await unnamedControls(page), [], "bedienelementen zonder naam op het loginscherm");
  await keyboardReach(page, ["Aanmelden", "Wachtwoord vergeten"], vp);
  await page.getByRole("button", { name: /aanmelden|inloggen/i }).first().click();
  const alert = alerts(page);
  await alert.waitFor();
  assert.match(await alert.innerText(), /E-mailadres of wachtwoord klopt niet\./);
  assert.equal(state.calls.filter((c) => c.key === "COGNITO").length, 1);
  assert.match(JSON.stringify(state.calls[0].body), /fiets@example\.test/);
  expectNoStrays(state, "login");
});

test("route openen via de zijbalk en met toetsenbord", async ({ page, url, vp }) => {
  const state = await installBackend(page);
  await openHome(page, url);
  if (vp.mobile) await page.getByRole("button", { name: "Open navigatie" }).first().click();
  await page.getByRole("navigation", { name: "Gesprekken en routes" }).getByRole("button", { name: /Berendries-lus/ }).click();
  await page.waitForURL(/\/routes\/r1\/?$/);
  await page.getByRole("heading", { level: 2, name: "Berendries-lus" }).waitFor();
  assert.ok(await page.getByLabel("Routedetails").getByText("30.0 km").first().isVisible(), "afstand zichtbaar");
  assert.equal(await page.title(), "Berendries-lus — Lusmaker");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { level: 2, name: "Berendries-lus" }).waitFor();
  assert.deepEqual(await unnamedControls(page), [], "bedienelementen zonder naam op de routepagina");
  expectNoStrays(state, "route openen");
});

test("routepagina: toetsenbord, focus en namen", async ({ page, url, vp }) => {
  const state = await installBackend(page);
  await openRoute(page, url);
  const stops = await keyboardReach(page, ["Download GPX", "Download FIT", "Deel", "Gewenste afstand", "Bereken opnieuw", "Plaats vermijden"], vp);
  assert.ok(stops.length > 5);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 0, `[${vp.name}] horizontaal scrollen (${overflow}px te breed)`);
  expectNoStrays(state, "routepagina");
});

test("route laden: foutmelding wordt aangekondigd", async ({ page, url }) => {
  const state = await installBackend(page, { handlers: { "GET /api/routes/r1": () => json(404, { error: "Route niet gevonden." }) } });
  await page.goto(`${url}/routes/r1/`, { waitUntil: "domcontentloaded" });
  const alert = alerts(page);
  await alert.waitFor();
  assert.match(await alert.innerText(), /Route niet gevonden\./);
  await page.getByRole("button", { name: "Sluit foutmelding" }).click();
  await alert.waitFor({ state: "detached" });
  expectNoStrays(state, "route laden");
});

test("afstand aanpassen via Gewenste afstand", async ({ page, url }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/r1/adjust": async ({ body, state: s }) => {
        await gate;
        s.route = { ...s.route, total_km: body.target_km, revision: s.route.revision + 1, constraints: { doel_km: body.target_km, waarschuwingen: [] } };
        return json(200, { route: s.route });
      },
    },
  });
  await openRoute(page, url);
  const field = page.getByLabel("Gewenste afstand (km)");
  assert.equal(await field.inputValue(), "30");
  await field.fill("42");
  await page.getByRole("button", { name: "Bereken opnieuw" }).click();
  // Laadstatus: knop vergrendeld en de voortgang wordt als status aangekondigd.
  await page.getByRole("button", { name: "Route aanpassen…" }).waitFor();
  assert.ok(await field.isDisabled(), "veld vergrendeld tijdens berekenen");
  await page.getByRole("status").filter({ hasText: "Route aanpassen" }).waitFor();
  release();
  await page.getByLabel("Routedetails").getByText("42.0 km").first().waitFor();
  const call = state.calls.find((c) => c.key === "POST /api/routes/r1/adjust");
  assert.deepEqual(call.body, { target_km: 42, expected_revision: 1 });
  assert.equal(await field.inputValue(), "42");
  // Stap-knoppen sturen ook de nieuwe revisie mee.
  await page.getByRole("button", { name: /^\+?\s*5 km$/ }).first().click();
  await page.getByLabel("Routedetails").getByText("47.0 km").first().waitFor();
  assert.equal(state.calls.filter((c) => c.key === "POST /api/routes/r1/adjust").at(-1).body.expected_revision, 2);
  expectNoStrays(state, "afstand");
});

test("revision-conflict (409) toont melding en laadt nieuwste versie", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/r1/adjust": ({ state: s }) => { s.route = { ...s.route, revision: 7, total_km: 33 }; return json(409, { error: "revision conflict", code: "revision_conflict" }); },
    },
  });
  await openRoute(page, url);
  await page.getByLabel("Gewenste afstand (km)").fill("50");
  await page.getByRole("button", { name: "Bereken opnieuw" }).click();
  const alert = alerts(page);
  await alert.waitFor();
  assert.match(await alert.innerText(), /De route is intussen gewijzigd\. Je ziet nu de nieuwste versie/);
  await page.getByLabel("Routedetails").getByText("33.0 km").first().waitFor(); // verse versie opnieuw geladen
  assert.equal(state.calls.filter((c) => c.key === "GET /api/routes/r1").length >= 2, true);
  expectNoStrays(state, "409");
});

test("delen en intrekken", async ({ page, url, vp }) => {
  const state = await installBackend(page);
  await openRoute(page, url);
  const confirms = [];
  page.on("dialog", (dialog) => { confirms.push(dialog.message()); void dialog.accept(); });
  await page.getByRole("button", { name: "Deel", exact: true }).click();
  const link = page.getByRole("link", { name: "http://share.e2e.test/s/tok123" });
  await link.waitFor();
  assert.match(confirms[0], /precieze startpunt/);
  assert.equal(await link.getAttribute("href"), "http://share.e2e.test/s/tok123");
  await page.getByRole("button", { name: "Deellink kopiëren" }).waitFor();
  assert.deepEqual(await unnamedControls(page), []);
  await page.getByRole("button", { name: "Stop delen" }).click();
  await link.waitFor({ state: "detached" });
  assert.equal(await page.getByRole("button", { name: "Stop delen" }).count(), 0);
  assert.deepEqual(state.calls.map((c) => c.key).filter((k) => k.includes("share")), ["POST /api/routes/r1/share", "DELETE /api/routes/r1/share"]);
  // Weigeren van de bevestiging maakt geen link.
  page.removeAllListeners("dialog");
  page.on("dialog", (dialog) => void dialog.dismiss());
  await page.getByRole("button", { name: "Deel", exact: true }).click();
  await wait(200);
  assert.equal(state.calls.filter((c) => c.key === "POST /api/routes/r1/share").length, 1, `[${vp.name}] geweigerde bevestiging mag niet delen`);
  expectNoStrays(state, "delen");
});

test("delen mislukt: fout wordt aangekondigd", async ({ page, url }) => {
  const state = await installBackend(page, { handlers: { "POST /api/routes/r1/share": () => json(500, { error: "Deellink maken is mislukt." }) } });
  await openRoute(page, url);
  page.on("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Deel", exact: true }).click();
  assert.match(await alerts(page).innerText(), /Deellink maken is mislukt\./);
  expectNoStrays(state, "delen fout");
});

test("GPX- en FIT-download geven een downloadevent", async ({ page, url }) => {
  const state = await installBackend(page);
  await openRoute(page, url);
  const [gpx] = await Promise.all([page.waitForEvent("download", { timeout: TIMEOUT }), page.getByRole("button", { name: "Download GPX" }).click()]);
  assert.equal(gpx.suggestedFilename(), "Berendries-lus.gpx");
  const [fit] = await Promise.all([page.waitForEvent("download", { timeout: TIMEOUT }), page.getByRole("button", { name: "Download FIT" }).click()]);
  assert.equal(fit.suggestedFilename(), "Berendries-lus.fit");
  assert.deepEqual(state.calls.map((c) => c.key).filter((k) => /gpx|fit/.test(k)), ["GET /api/routes/r1/gpx", "GET /api/routes/r1/fit"]);
  expectNoStrays(state, "download");
});

test("download mislukt: fout wordt aangekondigd", async ({ page, url }) => {
  const state = await installBackend(page, { handlers: { "GET /api/routes/r1/gpx": () => json(500, { error: "kapot" }) } });
  await openRoute(page, url);
  await page.getByRole("button", { name: "Download GPX" }).click();
  assert.match(await alerts(page).innerText(), /Routebestand kon niet worden geladen\./);
  expectNoStrays(state, "download fout");
});

test("snelle planner: validatie, voortgang en buiten_gebied (422)", async ({ page, url, vp }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let attempts = 0;
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/stream": async () => {
        attempts += 1;
        if (attempts === 1) { await gate; return json(422, { error: "Deze startplaats ligt buiten het gedekte gebied.", code: "buiten_gebied" }); }
        return sse([["progress", { stage: "route", message: "Route wordt berekend" }], ["result", { status: "ready", draft: "r1", km: 41.2, constraints: { voldaan: true, waarschuwingen: [] } }]]);
      },
    },
  });
  await openHome(page, url);
  assert.deepEqual(await unnamedControls(page), [], "bedienelementen zonder naam in de planner");
  const start = page.getByLabel("Startplaats");
  // Leeg verzenden: de browser blokkeert en het verplichte veld is ongeldig.
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  assert.equal(await start.evaluate((el) => el.validity.valueMissing), true);
  assert.equal(attempts, 0, "geen request bij een leeg verplicht veld");
  await start.fill("Parijs");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("button", { name: "Route wordt berekend…" }).waitFor();
  await page.getByRole("status").filter({ hasText: "Verbinding maken met het routeatelier" }).waitFor();
  release();
  const alert = alerts(page).filter({ hasText: "buiten het gedekte gebied" });
  await alert.waitFor();
  assert.match(await alert.innerText(), /Pas je startplaats aan en probeer opnieuw\./);
  assert.equal(await start.inputValue(), "Parijs", "invoer blijft bewaard");
  assert.ok(await start.isEnabled(), "invoer blijft bewerkbaar");
  // Nieuwe poging met een geldige plaats lukt en kondigt het resultaat aan.
  await start.fill("Wetteren");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("status").filter({ hasText: "Je route is klaar" }).waitFor();
  assert.ok(await page.getByRole("button", { name: "Bekijk mijn route" }).isVisible());
  assert.equal(state.calls.filter((c) => c.key === "POST /api/routes/stream").length, 2);
  const ids = state.calls.filter((c) => c.key === "POST /api/routes/stream").map((c) => c.body.request_id);
  assert.notEqual(ids[0], ids[1], `[${vp.name}] nieuwe invoer krijgt een nieuw request_id`);
  expectNoStrays(state, "planner");
});

test("snelle planner: streamfout met buiten_gebied-code", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/stream": () => sse([["error", { error: "Start ligt buiten het gedekte gebied.", code: "buiten_gebied" }]]) },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Berlijn");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  const alert = alerts(page).filter({ hasText: "buiten het gedekte gebied" });
  await alert.waitFor();
  assert.match(await alert.innerText(), /Pas je startplaats aan/);
  assert.equal(await page.getByRole("button", { name: "Nieuwe poging voorbereiden" }).count(), 0);
  expectNoStrays(state, "planner stream");
});

test("quotum bereikt (429 quota_exceeded) toont de servertekst", async ({ page, url }) => {
  const text = "Je hebt vandaag al 5 routes gemaakt. Morgen om 00:00 kun je opnieuw plannen.";
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/stream": () => json(429, { error: text, code: "quota_exceeded" }, { "retry-after": "3600" }) },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Wetteren");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  const alert = alerts(page).filter({ hasText: "Morgen om 00:00" });
  await alert.waitFor();
  assert.equal((await alert.innerText()).trim(), text);
  assert.equal(await page.getByText("Het is even te druk").count(), 0, "geen generieke tekst bij quota_exceeded");
  expectNoStrays(state, "quota");
});

test("429 zonder quotumcode toont de generieke wachttijd", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/stream": () => json(429, { error: "slow down" }, { "retry-after": "120" }) },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Wetteren");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  assert.match(await alerts(page).innerText(), /Het is even te druk\. Probeer over 2 minuten opnieuw\./);
  expectNoStrays(state, "429 generiek");
});

test("chatscherm: toetsenbord en namen van iconknoppen", async ({ page, url, vp }) => {
  const state = await installBackend(page);
  await openHome(page, url);
  assert.deepEqual(await unnamedControls(page), []);
  const stops = await keyboardReach(page, [vp.mobile ? "Open navigatie" : "Nieuwe route", "Maak mijn route"], vp);
  assert.ok(stops.some((s) => s.name === "Bericht aan Lus" || s.tag === "textarea"), "composer bereikbaar");
  expectNoStrays(state, "chatscherm");
});

// --- Runner ---------------------------------------------------------------

const only = process.env.E2E_ONLY;
const started = Date.now();
const server = await startServer();
const browser = await chromium.launch();
let failures = 0;
try {
  // Warm de dev-compilatie op zodat geen enkele test op webpack wacht.
  const warm = await browser.newPage();
  await installBackend(warm);
  for (const p of ["/", "/?new=1", "/routes/r1/"]) { await warm.goto(`${server.url}${p}`, { waitUntil: "load" }).catch(() => undefined); await wait(1200); }
  await warm.close();

  for (const vp of VIEWPORTS) {
    for (const { name, fn } of tests) {
      if (only && !name.includes(only)) continue;
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile,
        acceptDownloads: true, serviceWorkers: "block", reducedMotion: "reduce", permissions: ["clipboard-read", "clipboard-write"],
      });
      const page = await context.newPage();
      page.setDefaultTimeout(TIMEOUT);
      const t0 = Date.now();
      try {
        await fn({ page, url: server.url, vp });
        console.log(`ok   [${vp.name}] ${name} (${Date.now() - t0} ms)`);
      } catch (error) {
        failures += 1;
        console.log(`FAIL [${vp.name}] ${name}\n     ${String(error.message).split("\n").join("\n     ")}`);
        if (process.env.E2E_DEBUG) console.log("     URL:", page.url(), "\n     TEKST:", (await page.locator("body").innerText().catch(() => "?")).slice(0, 400), "\n     FOUTEN:", JSON.stringify(page._e2e));
      } finally { await context.close(); }
    }
  }
} finally {
  await browser.close();
  server.stop();
}
console.log(`\n${failures ? `${failures} test(s) mislukt` : "alle tests geslaagd"} in ${((Date.now() - started) / 1000).toFixed(1)} s`);
process.exit(failures ? 1 : 0);
