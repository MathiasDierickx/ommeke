# Mobiele screenshots

`mobile-shots.mjs` rendert de gedeployde app als een iPhone 13 op een viewport
van 390×844. De PNG's komen in `e2e/shots/` terecht en worden niet door Git
gevolgd.

Installeer Chromium eenmalig na `npm install`:

```sh
npx playwright install chromium
```

Zonder tokens maakt de runner alleen `01-welcome.png`. Voor de ingelogde
screenshots zijn zowel het access token als het ID-token van dezelfde
reviewer-sessie nodig:

```sh
SHOTS_ACCESS_TOKEN='…' \
SHOTS_ID_TOKEN='…' \
npm run shots
```

De standaard-URL is `https://ommeke.vercel.app`. Een andere deploy en een
bekende route kunnen via extra omgevingsvariabelen worden gekozen:

```sh
SHOTS_BASE_URL='https://preview.example' \
SHOTS_ACCESS_TOKEN='…' \
SHOTS_ID_TOKEN='…' \
SHOTS_ROUTE_ID='…' \
npm run shots
```

Zonder `SHOTS_ROUTE_ID`, of wanneer die route niet kan worden geladen, legt de
runner de lijst **Mijn routes** vast. Tokens horen alleen in de shell of in
CI-secrets; zet ze nooit in dit script, een env-bestand of de repository.

## Suggestie voor CI

De bestaande workflows blijven bewust ongewijzigd. Een workflow kan na zijn
Vercel-deploy een job zoals deze toevoegen. Vervang `deploy` door de echte
job-id en laat `SHOTS_BASE_URL` eventueel uit de deploy-output komen.

```yaml
mobile-screenshots:
  needs: deploy
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: web
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: 20
        cache: npm
        cache-dependency-path: web/package-lock.json
    - run: npm ci
    - run: npx playwright install --with-deps chromium
    - run: npm run shots
      env:
        SHOTS_BASE_URL: ${{ needs.deploy.outputs.url }}
        SHOTS_ACCESS_TOKEN: ${{ secrets.SHOTS_ACCESS_TOKEN }}
        SHOTS_ID_TOKEN: ${{ secrets.SHOTS_ID_TOKEN }}
        SHOTS_ROUTE_ID: ${{ secrets.SHOTS_ROUTE_ID }}
    - uses: actions/upload-artifact@v4
      if: always()
      with:
        name: mobile-screenshots
        path: web/e2e/shots/*.png
        if-no-files-found: error
```
