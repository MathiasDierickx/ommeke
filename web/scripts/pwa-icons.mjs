// Maakt de PWA-iconen (192 en 512 px, maskable) uit public/favicon.svg.
// Gebruik: node scripts/pwa-icons.mjs public/favicon.svg public
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
const svg = readFileSync(process.argv[2], "utf8");
const out = process.argv[3];
const browser = await chromium.launch();
for (const size of [192, 512]) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  // Maskable: het beeldmerk in de veilige zone (80 %) op de merkkleur.
  await page.setContent(`<body style="margin:0;background:#183f30"><div style="width:${size}px;height:${size}px;display:grid;place-items:center"><div style="width:${size * 0.8}px;height:${size * 0.8}px">${svg.replace("<svg", '<svg style="width:100%;height:100%"')}</div></div></body>`);
  await page.screenshot({ path: `${out}/icon-${size}.png`, type: "png" });
  await page.close();
}
await browser.close();
