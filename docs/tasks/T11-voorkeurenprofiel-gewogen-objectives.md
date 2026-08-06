# T11 — Voorkeurenprofielen + gewogen objectives

## Waarom

Gebruikers denken niet in één objective. "Veel offroad én wat hoogtemeters,
kasseien vind ik leuk" = een gewichtenmix + voorkeuren. Dit wordt een
persistent profiel; T12 bouwt er de vraag-begeleiding (readiness) bovenop.

## 1. Profieldocument (`lusmaker/profiles.py`)

Opslag: `<HOME>/profiles/<naam>.json` (regio-onafhankelijk, dus HOME-root):

```json
{
  "naam": "standaard",
  "activiteit": "fietsen",
  "gewichten": {"hoogtemeters": 1.0, "offroad": 0.0, "populair": 0.0, "kort": 0.0},
  "voorkeuren": {
    "kasseien": null,
    "beton": null,
    "steenwegen": null,
    "vermijd_plaatsen": []
  },
  "historiek": []
}
```

- **`null` betekent ONBEKEND** en is betekenisvol (T12 stelt er vragen over);
  onderscheid met expliciet `"ok"` (= gevraagd, maakt de gebruiker niet uit).
- Waarden: kasseien/beton/steenwegen ∈ {null, "vermijd", "ok", "graag"}
  (steenwegen kent geen "graag"; valideer).
- API: `load(naam)` (ontbrekend → default-document), `save`, `list_all`,
  `apply_patch(naam, patch, bron)` — patch is een dict met dezelfde vorm;
  elke patch wordt met timestamp+bron aan `historiek` toegevoegd.
- Mapping profiel → routing-knoppen in één functie
  `routing_prefs(profiel) -> dict` : kasseien=="vermijd" → avoid_cobbles,
  beton=="vermijd" → avoid_concrete, steenwegen=="vermijd" → strict,
  activiteit "trail" → profile "trail". "graag" heeft GEEN routing-effect
  (alleen scoring, zie §2) — routing-boosts voor oppervlaktes maken routes
  kapot.

## 2. Gewogen scoring (`draft.py`)

- `optimize(..., objective=...)` accepteert naast de bestaande strings ook een
  gewichten-dict `{"hoogtemeters": .., "offroad": .., "populair": .., "kort": ..}`
  (genormaliseerd op som=1; negatieve gewichten → fout).
- Scorecomponenten per kandidaat, elk naar [0,1]:
  - `hoogtemeters`: (extra_hm / max(extra_km,0.3)) / 20, gecapt op 1
  - `offroad`: offroad-aandeel van de toevoeging (road_class-details van
    r1+r2+r3 resp. de rondrit-lob)
  - `populair`: aandeel punten in heat-cellen (heat.popular_cells; geen heat
    → component 0)
  - `kort`: 1 − extra_km / (budget_km op dat moment)
  - kasseien=="graag" in het meegegeven profiel: voeg component
    `kassei` (aandeel kassei-meters) toe met gewicht 0.15 bovenop de mix
    (documenteer dit gedrag).
- Score = Σ gewicht × component. Bestaande enkelvoudige objectives blijven
  werken als suikervorm: "hm" ≡ {"hoogtemeters":1}, "offroad" ≡
  {"offroad":1}, "hm-per-km" blijft zijn huidige pad (geen gedragswijziging).
- De **guards blijven hard**: budget, heen-en-weer, lus-toets — nooit
  onderdeel van de gewogen score.
- Benodigde data: r1/r2/r3 en round_trip-kandidaten met `details=True`
  opvragen wanneer een gewichten-dict actief is (offroad/kassei-meting).

## 3. CLI + intents

- `lus profile show|list|set` — `set` accepteert
  `--gewichten "hoogtemeters=0.5,offroad=0.5"` en `--kasseien graag` etc.
  (dunne wrapper om apply_patch, bron="cli").
- `lus draft new --profiel-naam <naam>`: draft krijgt `"profile_doc": naam`;
  route/optimize/suggest halen routing-prefs en gewichten uit het profiel
  (draft-eigen velden zoals avoid_cobbles blijven werken als override).
- `lus draft optimize --gewichten ...` overschrijft het profiel eenmalig.
- `intents.plan_route`: nieuw param `profiel_naam`; bestaand gedrag zonder
  profiel identiek (geen cassettebreuk: alle defaults ongewijzigd).

## 4. MCP

Tools `get_profile(naam="standaard")`, `update_profile(naam, patch)`,
`list_profiles()`. `new_draft`/`plan_route` krijgen `profiel_naam`-param.
Toolaantallen in tests bijwerken (vol 23, lite blijft 7 — profieltools horen
in T12 óók lite te worden, maar dat doet T12).

## Tests (puur)

- profieldocument: load-default, apply_patch + historiek, validatie van
  waarden, routing_prefs-mapping incl. "graag"-heeft-geen-routing-effect.
- normalisatie + score: synthetische kandidaten, gewichten-mix kiest anders
  dan enkelvoudige objectives; som-normalisatie; foutpaden.
- gewichten-parsing CLI-string.
- Bestaande cassettes MOETEN groen blijven (geen default-gedragswijziging).

## DoD

`python -m tests.run` groen incl. cassettes; docs (README, CLAUDE.md kort —
T12 herschrijft de flow); kleine commits; niet pushen; geen netwerk/docker.
