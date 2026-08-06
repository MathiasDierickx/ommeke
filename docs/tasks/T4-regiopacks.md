# T4 — Regiopacks (M4): Lusmaker buiten de Vlaamse Ardennen

## Waarom

PRODUCT.md M4. Iemand moet "Zeeland" kunnen vragen. Elke regio krijgt eigen
data + eigen GraphHopper-graaf; drafts weten bij welke regio ze horen.

## Concept

- Regioregister: `~/.lusmaker/regions.json` — per regio:
  `{"slug", "geofabrik": "europe/netherlands/zeeland", "bbox": [minlat, minlon, maxlat, maxlon], "gh_port": 8990, ...}`.
- Datalayout per regio: `~/.lusmaker/regions/<slug>/{data,cache,gh,heat}` —
  zelfde substructuur als de huidige globale mappen.
- **Backwards compat**: bestaande installatie wordt regio `vlaanderen`.
  Commando `lus region migrate-legacy` verplaatst de huidige `data/cache/gh/
  heat`-mappen naar `regions/vlaanderen/` en registreert die met de huidige
  BBOX en poort 8989. Zolang er geen regions.json bestaat, gedragen alle
  commando's zich exact zoals nu (legacy-paden) — niets breekt.
- Default-regio in regions.json (`"default": "vlaanderen"`); override per
  commando met `--region <slug>` en env `LUSMAKER_REGION`.

## Commando's

- `lus region add <slug> --geofabrik <pad> --bbox minlat,minlon,maxlat,maxlon`
  → downloadt extract + DEM-tegels (tegels afleiden uit de bbox: alle
  1°×1°-graden die de bbox raakt, skadi-formaat zoals nu), bouwt
  extract/gazetteer-cache en draait klimdetectie (`detect_auto`); schrijft
  GH-config voor de regio (poort = laagste vrije vanaf 8989) en werkt
  `docker-compose.regions.yml` bij (één service per regio, containernaam
  `lusmaker-gh-<slug>`, mounts naar de regiomappen zoals de bestaande
  compose incl. de default-gh-mount-workaround). De curated climbs.yaml is
  Vlaanderen-specifiek: gebruik hem alleen voor regio `vlaanderen`; andere
  regio's draaien puur op auto-detectie.
- `lus region list` — regio's + status (data aanwezig, GH bereikbaar).
- `lus region default <slug>`.
- `lus region migrate-legacy` (zie boven).

## Doorwerking

- `config.py`: paden regiobewust maken via een `Region`-object of module-
  functies `paths(region)`; minimale diff in de rest van de code — modules
  vragen paden/GH-URL op i.p.v. module-constanten te importeren waar nodig.
  Kies de kleinste refactor die werkt; documenteer de keuze in de commit.
- `gh.py`: GH-URL per regio (poort uit regions.json).
- `draft.new` slaat `"region"` op; alle draft-commando's resolven de regio
  uit de draft zelf (niet uit de default).
- MCP-tools: `new_draft` en `list_climbs` krijgen optionele `region`-param;
  `status` en een nieuwe tool `list_regions` tonen het register.
  **tests/test_mcp.py verwacht dan 16 tools — bijwerken.**
- `setup`/`build` (bestaande commando's) werken op de default-regio.

## Niet in scope (noteer als beperking in README)

- Grensoverschrijdende routes over twee regio's heen (vraagt gemergde
  extract; v2-idee: meerdere geofabrik-slugs per regio mergen met pyosmium).
- Automatisch bbox afleiden uit de Geofabrik-polygon.

## Tests (puur)

- Registerlogica: add/list/default/poorttoewijzing tegen een tempdir
  (LUSMAKER_HOME), zonder downloads (injecteer een no-op downloader of test
  alleen de registratielaag).
- DEM-tegelberekening uit bbox (pure functie): Zeeland-bbox
  (51.2, 3.4, 51.8, 4.3) → {N51E003, N51E004}.
- Legacy-gedrag: zonder regions.json blijven de bestaande paden gelden.

## DoD

- `.venv/bin/python -m tests.run` groen; bestaande commando's ongewijzigd
  gedrag zonder regions.json.
- README: regiosectie met Zeeland als voorbeeld; PRODUCT.md M4 afvinken.
- Kleine commits; niet pushen. Geen downloads of docker-commando's draaien.
