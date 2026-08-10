import { mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium, devices } from "playwright";

const DEFAULT_BASE_URL = "https://ommeke.vercel.app";
const SESSION_KEY = "lusmaker.auth";
const NAVIGATION_TIMEOUT_MS = 60_000;
const TILE_TIMEOUT_MS = 30_000;
const POLYLINE_SETTLE_MS = 1_500;
const iPhone13 = {
  ...devices["iPhone 13"],
  viewport: { width: 390, height: 844 },
  reducedMotion: "reduce",
};

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const shotsDirectory = path.join(scriptDirectory, "shots");
const shotPaths = {
  welcome: path.join(shotsDirectory, "01-welcome.png"),
  route: path.join(shotsDirectory, "02-route.png"),
  routes: path.join(shotsDirectory, "02-routes.png"),
  menu: path.join(shotsDirectory, "03-menu.png"),
};

function baseUrl() {
  const value = (process.env.SHOTS_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("SHOTS_BASE_URL moet een http(s)-URL zijn");
  }
  return value;
}

function log(message) {
  console.log(`[mobile-shots] ${message}`);
}

async function prepareShotsDirectory() {
  await mkdir(shotsDirectory, { recursive: true });
  await Promise.all(Object.values(shotPaths).map((file) => rm(file, { force: true })));
}

async function openPage(context, url, selector) {
  const page = await context.newPage();
  page.setDefaultTimeout(NAVIGATION_TIMEOUT_MS);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await page.waitForSelector(selector, { state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  return page;
}

async function captureWelcome(browser, url) {
  const context = await browser.newContext(iPhone13);
  try {
    const page = await openPage(context, url, ".login-shell");
    await page.screenshot({ path: shotPaths.welcome });
    log(`welkomstscherm opgeslagen: ${path.relative(process.cwd(), shotPaths.welcome)}`);
  } finally {
    await context.close();
  }
}

async function authenticatedContext(browser, accessToken, idToken) {
  const context = await browser.newContext(iPhone13);
  const session = {
    accessToken,
    idToken,
    expiresAt: Date.now() + 60 * 60 * 1_000,
  };
  await context.addInitScript(
    ({ key, value }) => sessionStorage.setItem(key, JSON.stringify(value)),
    { key: SESSION_KEY, value: session },
  );
  return context;
}

async function openWorkspace(context, url) {
  return openPage(context, url, ".composer");
}

async function openMobileMenu(page) {
  await page.locator(".mobile-menu").click();
  await page.waitForSelector(".left-open .sidebar", { state: "visible" });
}

async function captureRoute(page, url, routeId) {
  const routeUrl = `${url}/routes/${encodeURIComponent(routeId)}/`;
  await page.goto(routeUrl, { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await page.waitForSelector(".route-sheet", { state: "visible", timeout: NAVIGATION_TIMEOUT_MS });

  if (await page.locator(".leaflet-container").count()) {
    try {
      await page.waitForSelector(".leaflet-tile-loaded", {
        state: "visible",
        timeout: TILE_TIMEOUT_MS,
      });
    } catch {
      log("kaarttiles niet tijdig geladen; routedetail wordt zonder volledige tiles vastgelegd");
    }
    await page.waitForTimeout(POLYLINE_SETTLE_MS);
  }

  await page.screenshot({ path: shotPaths.route });
  log(`routedetail opgeslagen: ${path.relative(process.cwd(), shotPaths.route)}`);
}

async function captureRoutesList(page, url) {
  await page.goto(`${url}/`, { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await page.waitForSelector(".composer", { state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  await openMobileMenu(page);
  await page.getByText("Mijn routes", { exact: true }).waitFor({ state: "visible" });
  await page.locator(".sidebar").screenshot({ path: shotPaths.routes });
  log(`routelijst opgeslagen: ${path.relative(process.cwd(), shotPaths.routes)}`);
}

async function captureMenu(page, url) {
  await page.goto(`${url}/`, { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await page.waitForSelector(".composer", { state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  await openMobileMenu(page);
  await page.screenshot({ path: shotPaths.menu });
  log(`open drawer opgeslagen: ${path.relative(process.cwd(), shotPaths.menu)}`);
}

async function main() {
  const url = baseUrl();
  const accessToken = process.env.SHOTS_ACCESS_TOKEN;
  const idToken = process.env.SHOTS_ID_TOKEN;
  const routeId = process.env.SHOTS_ROUTE_ID;

  await prepareShotsDirectory();
  const browser = await chromium.launch();
  try {
    await captureWelcome(browser, url);

    if (!accessToken || !idToken) {
      const missing = [
        !accessToken ? "SHOTS_ACCESS_TOKEN" : null,
        !idToken ? "SHOTS_ID_TOKEN" : null,
      ].filter(Boolean).join(" en ");
      log(`${missing} ontbreekt; ingelogde screenshots worden overgeslagen`);
      return;
    }

    const context = await authenticatedContext(browser, accessToken, idToken);
    try {
      const page = await openWorkspace(context, `${url}/`);

      if (routeId) {
        try {
          await captureRoute(page, url, routeId);
        } catch (error) {
          log(`route ${routeId} kon niet worden getoond (${error.message}); routelijst wordt vastgelegd`);
          await captureRoutesList(page, url);
        }
      } else {
        log("SHOTS_ROUTE_ID ontbreekt; 'Mijn routes' wordt vastgelegd");
        await captureRoutesList(page, url);
      }

      await captureMenu(page, url);
    } finally {
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`[mobile-shots] fout: ${error.stack || error.message}`);
  process.exitCode = 1;
});
