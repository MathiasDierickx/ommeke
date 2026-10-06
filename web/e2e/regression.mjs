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
    state.calls.push({ key, body, url: request.url() });
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
      const container = el.closest("label, .composer, .start-input, .distance-form, .avoid-place, .auth-field, .library-filters, .adjust-row, form");
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
  await page.getByRole("heading", { name: /^Waar wil je/ }).waitFor();
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
  assert.ok(await page.getByLabel("Routedetails").getByText("30 km").first().isVisible(), "afstand zichtbaar");
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

test("routeconcept met vragen afmaken vanaf routepagina", async ({ page, url }) => {
  const questions = [
    { id: "heuvels", vraag: "Hoeveel heuvels wil je?", reden: "Je voorkeur is nog onbekend.", opties: { zoek: {}, ok: {}, vlak: {} } },
    { id: "ondergrond", vraag: "Welke ondergrond?", opties: { verhard: {}, ok: {}, onverhard: {} } },
  ];
  const state = await installBackend(page, { handlers: {
    "GET /api/routes/r1": ({ state: s }) => json(200, { route: s.route }),
    "POST /api/routes/r1/answers/stream": ({ body, state: s }) => {
      assert.deepEqual(body.antwoorden, { heuvels: "zoek", ondergrond: "verhard" });
      assert.match(body.request_id, /^[A-Za-z0-9_-]{8,128}$/);
      s.route = { ...s.route, ready: true, vragen: [], total_km: 60, geometry: { points: [[50, 3]], climbs: [], start: null }, revision: s.route.revision + 1 };
      return sse([["progress", { stage: "routing", message: "Route berekenen" }], ["result", { status: "ready", draft: "r1" }]]);
    },
  } });
  state.route = { ...state.route, ready: false, total_km: null, elevation_gain_m: null, download_url: null,
    constraints: { doel_km: 60, maximum_is_hard: true, maximum_km: 63, waarschuwingen: [] }, vragen: questions };
  await openRoute(page, url);
  await page.getByText("Deze route wacht nog op je keuzes").waitFor();
  await page.getByRole("radio", { name: "Graag heuvels" }).check();
  await page.getByRole("radio", { name: "Liever verhard" }).check();
  await page.getByRole("button", { name: "Maak mijn route met deze keuzes" }).click();
  await page.getByRole("button", { name: "Download GPX" }).waitFor();
  assert.ok(state.calls.filter(call => call.key === "GET /api/routes/r1").length >= 2, "detailroute na antwoorden opnieuw geladen");
  assert.deepEqual(state.calls.map(call => call.key).filter(key => key.includes("answers/stream")), ["POST /api/routes/r1/answers/stream"]);
  expectNoStrays(state, "routeconcept afmaken");
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
  await page.getByLabel("Routedetails").getByText("42 km").first().waitFor();
  const call = state.calls.find((c) => c.key === "POST /api/routes/r1/adjust");
  const { request_id: adjustId, ...adjustBody } = call.body;
  assert.deepEqual(adjustBody, { target_km: 42, expected_revision: 1 });
  assert.match(adjustId, /^[A-Za-z0-9_-]{8,128}$/, "stabiel verzoeknummer per aanpassing");
  assert.equal(await field.inputValue(), "42");
  // Stap-knoppen sturen ook de nieuwe revisie mee.
  await page.getByRole("button", { name: /^\+?\s*5 km$/ }).first().click();
  await page.getByLabel("Routedetails").getByText("47 km").first().waitFor();
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
  await page.getByLabel("Routedetails").getByText("33 km").first().waitFor(); // verse versie opnieuw geladen
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
  // Een geslaagde download mag geen foutmelding achterlaten (bv. "Illegal invocation").
  await page.waitForTimeout(300);
  assert.equal(await alerts(page).count(), 0, `onverwachte melding: ${await alerts(page).allInnerTexts()}`);
  assert.deepEqual(state.calls.map((c) => c.key).filter((k) => /gpx|fit/.test(k)), ["GET /api/routes/r1/gpx", "GET /api/routes/r1/fit"]);
  expectNoStrays(state, "download");
});

test("download neemt de actuele POI-filter mee", async ({ page, url }) => {
  const state = await installBackend(page);
  state.route.geometry = {
    points: [[51, 3], [51, 3.02]], climbs: [], elevation: [],
    pois: [{id: "node/1", kind: "cafe", name: "Café", lat: 51, lon: 3.01, at_km: 0.7}],
  };
  await page.route("https://*.tile.openstreetmap.org/**", route => route.fulfill({status: 200, contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII=", "base64")}));
  await openRoute(page, url);
  const filter = page.getByLabel("Onderweg");
  await filter.waitFor({timeout: TIMEOUT});
  for (const kind of ["cafe", "geen", "alle"]) {
    await filter.selectOption(kind);
    for (const format of ["GPX", "FIT"]) {
      await Promise.all([page.waitForEvent("download", {timeout: TIMEOUT}), page.getByRole("button", {name: `Download ${format}`}).click()]);
      const call = state.calls.filter(c => c.key === `GET /api/routes/r1/${format.toLowerCase()}`).at(-1);
      assert.equal(new URL(call.url).searchParams.get("poi"), kind === "alle" ? null : kind);
    }
  }
  expectNoStrays(state, "POI-download");
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

// Achtergrondladingen van de bibliotheek (gesprekken/routes) tellen niet mee.
const actionCalls = (state) => state.calls.filter((c) => !/^GET \/api\/(conversations|routes)$/.test(c.key)).length;

test("locatie geweigerd: melding, focus op startplaats en geen API-call", async ({ page, url }) => {
  const state = await installBackend(page);
  await page.context().grantPermissions([]);
  await openHome(page, url);
  const before = actionCalls(state);
  const locate = page.getByRole("button", { name: "Mijn locatie" });
  await locate.click();
  const alert = alerts(page);
  await alert.waitFor();
  assert.match(await alert.innerText(), /Locatie kon niet worden opgehaald\. Vul je startplaats in\./);
  assert.ok(await locate.isEnabled(), "locatieknop is na weigering weer bruikbaar");
  assert.equal(await page.getByLabel("Startplaats").evaluate((el) => el === document.activeElement), true, "focus gaat naar Startplaats");
  assert.equal(actionCalls(state), before, "locatie ophalen doet geen API-call");
  expectNoStrays(state, "locatie geweigerd");
});

test("locatie ontbreekt: melding, focus op startplaats en geen API-call", async ({ page, url }) => {
  const state = await installBackend(page);
  await page.addInitScript(() => { Object.defineProperty(navigator, "geolocation", { configurable: true, value: undefined }); });
  await openHome(page, url);
  const before = actionCalls(state);
  const locate = page.getByRole("button", { name: "Mijn locatie" });
  await locate.click();
  const alert = alerts(page);
  await alert.waitFor();
  assert.match(await alert.innerText(), /Locatie is niet beschikbaar\. Vul je startplaats in\./);
  assert.ok(await locate.isEnabled(), "locatieknop blijft bruikbaar");
  assert.equal(await page.getByLabel("Startplaats").evaluate((el) => el === document.activeElement), true, "focus gaat naar Startplaats");
  assert.equal(actionCalls(state), before, "ontbrekende locatievoorziening doet geen API-call");
  expectNoStrays(state, "locatie ontbreekt");
});

test("planner houdt invoer vast terwijl de bibliotheek nog laadt", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: {
      "GET /api/conversations": async () => { await wait(4000); return json(200, { conversations: [] }); },
      "GET /api/routes": async ({ state: s }) => { await wait(4000); return json(200, { routes: [s.route], next_cursor: null }); },
    },
  });
  await page.goto(`${url}/?new=1`);
  await page.getByRole("heading", { name: /^Waar wil je/ }).waitFor();
  await page.getByRole("radio", { name: "Racefiets" }).check();
  await page.getByLabel("Startplaats").fill("Markt, Oudenaarde");
  await page.getByText(/1 van 1 routes/).first().waitFor({ state: "attached", timeout: TIMEOUT });
  await wait(500);
  assert.equal(await page.getByLabel("Startplaats").inputValue(), "Markt, Oudenaarde", "startplaats bleef staan");
  assert.equal(await page.getByRole("radio", { name: "Racefiets" }).isChecked(), true, "activiteit bleef staan");
  expectNoStrays(state, "laden");
});

test("startscherm: wie al typt, wordt niet naar de laatste route gestuurd", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: {
      "GET /api/routes": async ({ state: s }) => { await wait(3000); return json(200, { routes: [s.route], next_cursor: null }); },
    },
  });
  await page.goto(`${url}/`);
  await page.getByLabel("Startplaats").fill("Kluisbos");
  await page.getByText(/1 van 1 routes/).first().waitFor({ state: "attached", timeout: TIMEOUT });
  await wait(500);
  assert.equal(new URL(page.url()).pathname, "/", "blijft op het startscherm");
  assert.equal(await page.getByLabel("Startplaats").inputValue(), "Kluisbos", "invoer bleef staan");
  expectNoStrays(state, "landing na interactie");
});

test("startscherm zonder interactie landt op de laatste route", async ({ page, url }) => {
  const state = await installBackend(page);
  await page.goto(`${url}/`);
  await page.waitForURL(/\/routes\/r1\/?$/, { timeout: TIMEOUT });
  expectNoStrays(state, "landing");
});

test("snelle planner: voorstellen bij het resultaat toepassen via adjust", async ({ page, url }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const voorstellen = [
    { titel: "Voeg Molenberg toe", uitleg: "Ongeveer 2,0 km extra voor 60 hoogtemeters erbij.", adjust_route: { voeg_klimmen_toe: ["molenberg"], target_km: 43 } },
    { titel: "Voeg Kapelmuur toe", uitleg: "Ongeveer 4,0 km extra voor 70 hoogtemeters erbij.", adjust_route: { voeg_klimmen_toe: ["kapelmuur"], target_km: 45 } },
  ];
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/stream": () => sse([["result", { status: "ready", draft: "d1", km: 40.4, voorstellen, constraints: { voldaan: true, waarschuwingen: [] } }]]),
      // Na de eerste aanpassing geeft de backend verse voorstellen voor de nieuwe route; na de tweede geen meer.
      "POST /api/routes/d1/adjust": async ({ state: s }) => {
        await gate;
        const first = s.calls.filter((c) => c.key === "POST /api/routes/d1/adjust").length === 1;
        return json(200, first
          ? { route: { id: "d1", total_km: 42.6 }, voorstellen: [{ titel: "Voeg Paterberg toe", uitleg: "Ongeveer 1,5 km extra voor 50 hoogtemeters erbij.", adjust_route: { voeg_klimmen_toe: ["paterberg"], target_km: 44 } }] }
          : { route: { id: "d1", total_km: 44.1, constraints: { voldaan: false, waarschuwingen: ["Er paste geen extra lus die bij je wensen past."] } } });
      },
    },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Markt, Oudenaarde");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("heading", { name: "Je route is klaar" }).waitFor();
  const group = page.getByRole("group", { name: "Voorstellen voor je route" });
  assert.equal(await group.getByRole("button").count(), 2, "hooguit twee voorstellen");
  assert.match(await group.innerText(), /60 hoogtemeters/);
  await group.getByRole("button", { name: "Voeg Molenberg toe" }).click();
  await page.getByRole("status").filter({ hasText: "Ik voeg Molenberg toe en bereken je route opnieuw." }).waitFor();
  release();
  await page.getByText("Aangepast: Voeg Molenberg toe.").waitFor();
  assert.match(await page.locator(".quick-result").innerText(), /42,6 km/);
  const fresh = page.getByRole("group", { name: "Voorstellen voor je route" });
  await fresh.getByRole("button", { name: "Voeg Paterberg toe" }).waitFor();
  assert.equal(await fresh.getByRole("button").count(), 1, "alleen de verse voorstellen, niet de oude");
  assert.equal(await fresh.getByRole("button", { name: "Voeg Kapelmuur toe" }).count(), 0, "oude voorstellen vervallen na aanpassing");
  const call = state.calls.find((c) => c.key === "POST /api/routes/d1/adjust");
  const { request_id: proposalId, ...proposalBody } = call.body;
  assert.deepEqual(proposalBody, { voeg_klimmen_toe: ["molenberg"], target_km: 43 });
  assert.match(proposalId, /^[A-Za-z0-9_-]{8,128}$/, "voorstel stuurt een verzoeknummer mee");
  await fresh.getByRole("button", { name: "Voeg Paterberg toe" }).click();
  await page.getByText("Aangepast: Voeg Paterberg toe.").waitFor();
  assert.equal(await page.getByRole("group", { name: "Voorstellen voor je route" }).count(), 0, "geen voorstellen meer als de backend er geen geeft");
  assert.match(await page.locator(".quick-result").innerText(), /44,1 km/);
  await page.getByRole("heading", { name: "Route gevonden — controleer je wensen" }).waitFor();
  assert.ok(await page.getByText("Er paste geen extra lus die bij je wensen past.").isVisible());
  expectNoStrays(state, "voorstellen");
});

test("snelle planner: zonder voorstellen blijft het resultaat zoals het was", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/stream": () => sse([["result", { status: "ready", draft: "d1", km: 6.2, constraints: { voldaan: true, waarschuwingen: [] } }]]) },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Markt, Oudenaarde");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("heading", { name: "Je route is klaar" }).waitFor();
  assert.equal(await page.locator(".quick-proposals").count(), 0);
  expectNoStrays(state, "geen voorstellen");
});

const startplaatsQuestion = {
  id: "startplaats", vraag: "Welke Kluisbos bedoel je?", opties: {
    "0": { label: "Kluisbos (Kluisbergen)", patch: { start: { lat: 50.76, lon: 3.50, label: "Kluisbos (Kluisbergen)" } } },
    "1": { label: "Kluisbos (Halle)", patch: { start: { lat: 50.74, lon: 4.26, label: "Kluisbos (Halle)" } } },
  },
};

test("chat: voorstel toepassen via knop", async ({ page, url }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const conversation = { id: "c1", title: "Racefiets vanaf Kluisbos" };
  const content = 'Je route is klaar. Nog iets toevoegen?\n- GPX: [/tmp/lusmaker/exports/r1/route.gpx]\n- Preview: [/tmp/lusmaker/exports/r1/preview.html]\n1. Voeg Chemin du Bois toe `adjust_route(voeg_klimmen_toe=["auto-chemin-du-bois"], target_km=55)`';
  const oldMessage = { id: "old", conversation_id: "c1", role: "assistant", content, created_at: "2026-10-06", route_ids: ["r1"] };
  const newMessage = { ...oldMessage, id: "new" };
  let messages = [oldMessage];
  const proposal = { titel: "Voeg Chemin du Bois toe", uitleg: "Ongeveer 2,1 km extra voor 40 hoogtemeters erbij.", adjust_route: { voeg_klimmen_toe: ["auto-chemin-du-bois"], target_km: 55 } };
  const state = await installBackend(page, { handlers: {
    "GET /api/routes": ({ state: s }) => {
      const { voorstellen, ...compact } = s.route;
      return json(200, { routes: [compact] });
    },
    "GET /api/conversations/c1/messages": () => json(200, { conversation, messages }),
    "POST /api/conversations/c1/messages/stream": () => {
      messages = [oldMessage, newMessage];
      return sse([["result", { message: newMessage, route_ids: ["r1"] }]]);
    },
    "POST /api/routes/r1/adjust": async ({ body, state: s }) => {
      assert.deepEqual(body.voeg_klimmen_toe, ["auto-chemin-du-bois"]);
      assert.equal(body.target_km, 55);
      assert.match(body.request_id, /^[A-Za-z0-9_-]{8,128}$/);
      await gate;
      s.route = { ...s.route, total_km: 54.1, revision: 2, voorstellen: [] };
      return json(200, { route: s.route });
    },
  } });
  state.route = { ...state.route, total_km: 52, voorstellen: [proposal] };
  await page.goto(`${url}/chats/c1`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: proposal.titel, exact: true }).waitFor();
  assert.ok(state.calls.some(c => c.key === "GET /api/routes/r1"), "voorstellen opgehaald via routedetail");
  await page.getByLabel("Bericht aan Lus").fill("Wat kan ik nog toevoegen?");
  await page.getByRole("button", { name: "Verstuur bericht" }).click();
  await page.locator(".message-assistant").nth(1).waitFor();
  const group = page.getByRole("group", { name: "Voorstellen voor je route" });
  await group.getByRole("button", { name: proposal.titel, exact: true }).waitFor();
  assert.equal(await group.count(), 1, "alleen het laatste bericht toont voorstellen");
  assert.equal(await page.locator(".message-assistant").first().locator(".quick-proposals").count(), 0);
  assert.equal(await page.locator(".option-chips").count(), 0, "geen geraden voorstellen of bestandsknoppen");
  assert.match(await group.innerText(), /2,1 km extra voor 40 hoogtemeters/);
  for (const label of await page.locator(".messages button").allTextContents()) assert.doesNotMatch(label, /\/tmp|adjust_route|`/);
  const before = actionCalls(state);
  await group.getByRole("button", { name: proposal.titel, exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Ik voeg Chemin du Bois toe en bereken je route opnieuw." }).waitFor();
  assert.equal(await group.getByRole("button").isDisabled(), true);
  release();
  await page.locator(".route-made").last().getByText("54,1 km · bekijk kaart en downloads").waitFor();
  assert.equal(await group.count(), 0, "oude voorstellen verdwenen na aanpassing");
  assert.equal(actionCalls(state), before + 1, "voorstel doet alleen één adjust-POST");
  const calls = state.calls.filter(c => c.key === "POST /api/routes/r1/adjust");
  assert.equal(calls.length, 1);
  const { request_id, ...body } = calls[0].body;
  assert.deepEqual(body, proposal.adjust_route);
  assert.equal(state.calls.filter(c => c.key.endsWith("messages/stream")).length, 1);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".route-made").last().getByText("54,1 km · bekijk kaart en downloads").waitFor();
  assert.equal(await page.getByRole("group", { name: "Voorstellen voor je route" }).count(), 0);
  expectNoStrays(state, "chatvoorstel");
});

test("chat: open vragen als knoppen beantwoorden", async ({ page, url }) => {
  const conversation = { id: "c1", title: "Racefiets vanaf Kluisbos" };
  const oldMessage = { id: "old", conversation_id: "c1", role: "assistant", content: "Welke plek?\n0. **Kluisbos (Buizingen)** – lat 50.73 lon 4.26\n1. _Kluisbos_", created_at: "2026-10-06", route_ids: ["r1"] };
  const questions = [
    { id: "ondergrond", vraag: "Welke ondergrond?", opties: { verhard: {}, ok: {}, onverhard: {} } },
    { id: "heuvels", vraag: "Zoek je heuvels?", opties: { zoek: {}, ok: {}, vlak: {} } },
    { id: "fietspaden", vraag: "Wil je fietspaden?", opties: { belangrijk: {}, ok: {} } },
  ];
  let release;
  const refreshed = new Promise(resolve => { release = resolve; });
  const state = await installBackend(page, { handlers: {
    "GET /api/routes/r1": async ({ state: s }) => {
      if (s.route.ready) await refreshed;
      return json(200, { route: s.route });
    },
    "GET /api/conversations/c1/messages": () => json(200, { conversation, messages: [oldMessage] }),
    "POST /api/conversations/c1/messages/stream": () => sse([["result", { message: { ...oldMessage, id: "new" }, route_ids: ["r1"] }]]),
    "POST /api/routes/r1/answers/stream": async ({ body, state: s }) => {
      assert.match(body.request_id, /^[A-Za-z0-9_-]{8,128}$/);
      if (s.route.vragen[0].id === "startplaats") {
        assert.deepEqual(body.antwoorden, { startplaats: "0" });
        s.route = { ...s.route, vragen: questions, revision: 2 };
        return sse([["result", { status: "needs_input", draft: "r1" }]]);
      }
      assert.deepEqual(body.antwoorden, { ondergrond: "verhard", heuvels: "ok", fietspaden: "belangrijk" });
      s.route = { ...s.route, ready: true, vragen: [], total_km: 50, revision: 3 };
      return sse([["progress", { stage: "routing", message: "Je keuzes worden verwerkt." }], ["result", { status: "ready", draft: "r1" }]]);
    },
  } });
  state.route = { ...state.route, ready: false, total_km: null, vragen: [startplaatsQuestion] };
  await page.goto(`${url}/chats/c1`, { waitUntil: "domcontentloaded" });
  await page.getByRole("radio", { name: "Kluisbos (Kluisbergen)", exact: true }).waitFor();
  await page.getByLabel("Bericht aan Lus").fill("racefiets 50 km vanaf Kluisbos");
  await page.getByRole("button", { name: "Verstuur bericht" }).click();
  await page.locator(".message-assistant").nth(1).waitFor();
  assert.equal(await page.locator(".route-pending").count(), 1, "alleen het laatste bericht toont open vragen");
  assert.equal(await page.locator(".message-assistant").first().locator(".route-pending").count(), 0);
  assert.equal(await page.locator(".option-chips").count(), 0, "geen geraden modelopties bij gestructureerde vragen");
  for (const label of await page.locator(".messages button, .messages .choice-chip").allTextContents()) {
    assert.doesNotMatch(label, /\*\*|\blat\b/);
  }
  const before = actionCalls(state);
  await page.getByRole("radio", { name: "Kluisbos (Kluisbergen)", exact: true }).check();
  assert.equal(actionCalls(state), before, "een keuze maken verstuurt niets");
  await page.getByRole("button", { name: "Route berekenen", exact: true }).click();
  await page.getByRole("radiogroup", { name: "Welke ondergrond?" }).waitFor();
  const go = page.getByRole("button", { name: "Route berekenen", exact: true });
  assert.equal(await go.isDisabled(), true);
  await page.getByRole("radio", { name: "Liever verhard" }).check();
  await page.getByRole("radiogroup", { name: "Zoek je heuvels?" }).getByRole("radio", { name: "Maakt niet uit" }).check();
  assert.equal(await go.isDisabled(), true);
  await page.getByRole("radio", { name: "Liefst op fietspaden" }).check();
  await go.click();
  await page.getByRole("status").filter({ hasText: "Je keuzes worden verwerkt." }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Route wordt berekend…", exact: true }).isDisabled(), true);
  release();
  await page.locator(".route-made").last().getByText("50 km · bekijk kaart en downloads").waitFor();
  assert.equal(await page.locator(".route-pending").count(), 0);
  const calls = state.calls.filter(c => c.key.endsWith("answers/stream"));
  assert.equal(calls.length, 2, "één POST per reeks vragen");
  assert.notEqual(calls[0].body.request_id, calls[1].body.request_id);
  assert.equal(state.calls.filter(c => c.key.endsWith("messages/stream")).length, 1, "knopantwoorden gebruiken geen chatmodel");
  expectNoStrays(state, "chatvragen");
});

test("snelle planner: startplaats kiezen vóór vervolgvragen", async ({ page, url }) => {
  const state = await installBackend(page, { handlers: {
    "POST /api/routes/stream": () => sse([["result", { status: "needs_input", draft: "d1", vragen: [startplaatsQuestion] }]]),
    "POST /api/routes/d1/answers/stream": ({ body }) => {
      if (body.antwoorden.startplaats) {
        assert.deepEqual(body.antwoorden, { startplaats: "0" });
        return sse([["result", { status: "needs_input", draft: "d1", vragen: [
          { id: "heuvels", vraag: "Zoek je heuvels?", opties: { zoek: {}, ok: {}, vlak: {} } },
        ] }]]);
      }
      assert.deepEqual(body.antwoorden, { heuvels: "zoek" });
      return sse([["result", { status: "ready", draft: "d1", km: 40, constraints: { voldaan: true, waarschuwingen: [] } }]]);
    },
  } });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Kluisbos");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByText("Welke Kluisbos bedoel je?").waitFor();
  assert.equal(await page.getByRole("radiogroup", { name: "Welke Kluisbos bedoel je?" }).getByRole("radio").count(), 2);
  await page.getByRole("radio", { name: "Kluisbos (Kluisbergen)", exact: true }).check();
  await page.getByRole("button", { name: "Maak mijn route met deze keuzes" }).click();
  await page.getByText("Zoek je heuvels?").waitFor();
  await page.getByRole("radio", { name: "Graag heuvels" }).check();
  await page.getByRole("button", { name: "Maak mijn route met deze keuzes" }).click();
  await page.getByRole("heading", { name: "Je route is klaar" }).waitFor();
  const calls = state.calls.filter(c => c.key.endsWith("answers/stream"));
  assert.equal(calls.length, 2);
  assert.notEqual(calls[0].body.request_id, calls[1].body.request_id);
  expectNoStrays(state, "startplaats planner");
});

test("routepagina: startplaats met leesbare kandidaatknoppen", async ({ page, url }) => {
  const state = await installBackend(page, { handlers: {
    "GET /api/routes/r1": ({ state: s }) => json(200, { route: s.route }),
    "POST /api/routes/r1/answers/stream": ({ body, state: s }) => {
      assert.deepEqual(body.antwoorden, { startplaats: "1" });
      s.route = { ...s.route, start: "Kluisbos (Halle)", ready: true, vragen: [], total_km: 20,
        geometry: { points: [[50.74, 4.26]], climbs: [], start: null }, revision: s.route.revision + 1 };
      return sse([["result", { status: "ready", draft: "r1" }]]);
    },
  } });
  state.route = { ...state.route, ready: false, total_km: null, vragen: [startplaatsQuestion] };
  await openRoute(page, url);
  await page.getByText("Welke Kluisbos bedoel je?").waitFor();
  await page.getByRole("radio", { name: "Kluisbos (Halle)", exact: true }).check();
  await page.getByRole("button", { name: "Maak mijn route met deze keuzes" }).click();
  await page.getByRole("button", { name: "Download GPX" }).waitFor();
  assert.equal(state.route.start, "Kluisbos (Halle)");
  expectNoStrays(state, "startplaats routepagina");
});

test("snelle planner: situationele vragen samen beantwoorden en doorgaan", async ({ page, url }) => {
  const vragen = [
    { id: "ondergrond", vraag: "6,0 km van je verkenningsroute is onverhard. Blijf je liever op verharde wegen?", opties: { verhard: {}, ok: {}, onverhard: {} } },
    { id: "heuvels", vraag: "Het is hier heuvelachtig. Zoek je de heuvels op?", opties: { zoek: {}, ok: {}, vlak: {} } },
  ];
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/stream": () => sse([["result", { status: "needs_input", draft: "d1", conversation_id: "c9", vragen }]]),
      "POST /api/routes/d1/answers/stream": () => sse([["progress", { stage: "routing", message: "Ik verwerk je keuzes en bereken je lus opnieuw." }], ["result", { status: "ready", draft: "d1", km: 40.4, constraints: { voldaan: true, waarschuwingen: [] } }]]),
    },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Markt, Oudenaarde");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("heading", { name: "Nog even je wensen aanvullen" }).waitFor();
  const go = page.getByRole("button", { name: "Maak mijn route met deze keuzes" });
  assert.equal(await go.isDisabled(), true, "pas actief als alle vragen beantwoord zijn");
  await page.getByRole("radio", { name: "Liever verhard" }).check();
  assert.equal(await go.isDisabled(), true);
  await page.getByRole("radio", { name: "Liever vlak" }).check();
  await go.click();
  await page.getByRole("heading", { name: "Je route is klaar" }).waitFor();
  assert.match(await page.locator(".quick-result").innerText(), /40,4 km/);
  const call = state.calls.find((c) => c.key === "POST /api/routes/d1/answers/stream");
  assert.deepEqual(call.body.antwoorden, { ondergrond: "verhard", heuvels: "vlak" });
  assert.ok(call.body.request_id, "verzoeknummer voor idempotentie");
  expectNoStrays(state, "vragen");
});

test("snelle planner: fietspad- en oversteekvragen krijgen leesbare knoppen", async ({ page, url }) => {
  const vragen = [
    { id: "fietspaden", vraag: "Slechts 5% van je verkenningsroute is fietspad. Wil je zoveel mogelijk op fietspaden rijden?", opties: { belangrijk: {}, ok: {} } },
    { id: "oversteken", vraag: "Je verkenningsroute steekt 4 keer een drukke weg over. Wil je oversteken vermijden?", opties: { vermijd: {}, ok: {} } },
  ];
  const state = await installBackend(page, {
    handlers: {
      "POST /api/routes/stream": () => sse([["result", { status: "needs_input", draft: "d1", conversation_id: "c9", vragen }]]),
      "POST /api/routes/d1/answers/stream": () => sse([["result", { status: "ready", draft: "d1", km: 12.3, constraints: { voldaan: true, waarschuwingen: [] } }]]),
    },
  });
  await openHome(page, url);
  await page.getByLabel("Startplaats").fill("Markt, Oudenaarde");
  await page.getByRole("button", { name: "Maak mijn route" }).click();
  await page.getByRole("heading", { name: "Nog even je wensen aanvullen" }).waitFor();
  await page.getByRole("radio", { name: "Liefst op fietspaden" }).check();
  await page.getByRole("radio", { name: "Liever weinig oversteken" }).check();
  await page.getByRole("button", { name: "Maak mijn route met deze keuzes" }).click();
  await page.getByRole("heading", { name: "Je route is klaar" }).waitFor();
  const call = state.calls.find((c) => c.key === "POST /api/routes/d1/answers/stream");
  assert.deepEqual(call.body.antwoorden, { fietspaden: "belangrijk", oversteken: "vermijd" });
  expectNoStrays(state, "fietspaden en oversteken");
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

test("onbeantwoorde chatvraag na herladen: afgebroken opdracht biedt herstel", async ({ page, url }) => {
  const question = "Maak een fietsroute van 35 km vanaf Oudenaarde";
  const conversation = { id: "c1", title: question, updated_at: "2026-10-05T19:00:00Z" };
  const state = await installBackend(page, {
    handlers: {
      "GET /api/conversations": () => json(200, { conversations: [conversation] }),
      "GET /api/conversations/c1/messages": () => json(200, { conversation, messages: [{ id: "m1", conversation_id: "c1", role: "user", content: question, created_at: "2026-10-05T19:00:00Z" }] }),
      "GET /api/conversations/c1/requests/req-1": () => json(200, { status: "interrupted" }),
    },
  });
  await page.addInitScript((value) => { try { sessionStorage.setItem("ommeke-pending:c1", JSON.stringify(value)); } catch { /* */ } }, { id: "req-1", content: question, conversationId: "c1" });
  await page.goto(`${url}/chats/c1`);
  const notice = page.locator(".orphan-notice");
  await notice.getByText("kreeg geen antwoord").waitFor();
  assert.equal(await notice.getAttribute("role"), "status");
  assert.ok(await notice.getByRole("button", { name: "Vraag opnieuw stellen" }).isVisible());
  expectNoStrays(state, "orphan");
});

test("chatscherm: toetsenbord en namen van iconknoppen", async ({ page, url, vp }) => {
  const state = await installBackend(page);
  await openHome(page, url);
  assert.deepEqual(await unnamedControls(page), []);
  const stops = await keyboardReach(page, [vp.mobile ? "Open navigatie" : "Nieuwe route", "Maak mijn route"], vp);
  assert.ok(stops.some((s) => s.name === "Bericht aan Lus" || s.tag === "textarea"), "composer bereikbaar");
  expectNoStrays(state, "chatscherm");
});

test("Breng me terug stuurt de afsluitingszone mee", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/r1/reroute": () => json(200, { status: "ready", draft: "r1", revision: 2 }) },
  });
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 50.9, longitude: 3.6 });
  await openRoute(page, url);
  await page.getByText("Breng me terug", { exact: true }).click();
  const box = page.getByRole("checkbox", { name: "Afgesloten weg vermijden" });
  await box.check();
  await page.getByRole("button", { name: /Gebruik mijn locatie/ }).click();
  for (let i = 0; i < 50 && !state.calls.some((c) => c.key === "POST /api/routes/r1/reroute"); i++) await wait(100);
  assert.ok(state.calls.some((c) => c.key === "POST /api/routes/r1/reroute"), "reroute-call verwacht");
  const body = state.calls.find((c) => c.key === "POST /api/routes/r1/reroute").body;
  assert.deepEqual(body.closure, { lat: 50.9, lon: 3.6 });
  assert.equal(body.rest_km, "kortste");
  assert.equal(body.lat, 50.9);
  expectNoStrays(state, "terugweg met afsluiting");
});

test("Breng me terug zonder vinkje stuurt geen closure", async ({ page, url }) => {
  const state = await installBackend(page, {
    handlers: { "POST /api/routes/r1/reroute": () => json(200, { status: "ready", draft: "r1", revision: 2 }) },
  });
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 50.9, longitude: 3.6 });
  await openRoute(page, url);
  await page.getByText("Breng me terug", { exact: true }).click();
  await page.getByRole("button", { name: /Gebruik mijn locatie/ }).click();
  for (let i = 0; i < 50 && !state.calls.some((c) => c.key === "POST /api/routes/r1/reroute"); i++) await wait(100);
  assert.ok(state.calls.some((c) => c.key === "POST /api/routes/r1/reroute"), "reroute-call verwacht");
  const body = state.calls.find((c) => c.key === "POST /api/routes/r1/reroute").body;
  assert.equal("closure" in body, false);
  expectNoStrays(state, "terugweg zonder afsluiting");
});

test("offline: geopende route blijft beschikbaar en toont een badge", async ({ page, url, vp }) => {
  // Eigen context mét service worker (de standaardcontext blokkeert die).
  const context = await page.context().browser().newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile, reducedMotion: "reduce" });
  try {
    const tab = await context.newPage();
    tab.setDefaultTimeout(TIMEOUT);
    const geometry = {
      points: [[51.0, 3.8], [51.01, 3.82], [51.02, 3.8], [51.0, 3.78]], climbs: [], start: { lat: 51.0, lon: 3.8 },
      elevation: [{ km: 0, ele: 10 }, { km: 1, ele: 40 }, { km: 2, ele: 15 }],
    };
    const state = await installBackend(tab, { handlers: { "GET /api/routes/r1": ({ state }) => json(200, { route: { ...state.route, geometry } }) } });
    await openRoute(tab, url);
    await tab.waitForFunction(() => { try { return JSON.parse(localStorage.getItem("ommeke-offline-routes-v1") || "[]").some((r) => r.id === "r1" && r.auto); } catch { return false; } });
    await tab.locator(".offline-badge", { hasText: "Offline beschikbaar" }).first().waitFor({ state: "attached" });
    await tab.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
    // Wacht tot de worker deze pagina beheert (clients.claim).
    await tab.waitForFunction(() => !!navigator.serviceWorker.controller);
    await context.setOffline(true);
    await tab.goto(`${url}/routes/r1/`, { waitUntil: "domcontentloaded" });
    await tab.locator("#name", { hasText: "Berendries-lus" }).waitFor();
    assert.ok((await tab.locator("#line").getAttribute("d"))?.startsWith("M"), "routelijn getekend");
    assert.ok((await tab.locator("#height").getAttribute("d"))?.startsWith("M"), "hoogteprofiel getekend");
    await context.setOffline(false);
    assert.deepEqual(state.pageErrors, []);
  } finally { await context.close(); }
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
