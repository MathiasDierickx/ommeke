# T7 — Sport-profielen (M5): trail-lopen naast fietsen

## Waarom

"Maak een 10 km trail in Wetteren met veel hoogtemeters" vraagt het omgekeerde
van het fietsprofiel: paden, bos en onverhard opzoeken i.p.v. mijden.

## GraphHopper-kant (`gh_config.py`)

- Tweede profiel in config.yml:
  ```yaml
  profiles:
    - name: quiet
      custom_model_files: [bike.json, quiet.json]
    - name: trail
      custom_model_files: [foot.json, trail.json]
  ```
- `graph.encoded_values` uitbreiden met `foot_access, foot_priority,
  foot_average_speed` (hike_rating/mtb_rating staan er al).
- Nieuw custom model `trail.json` (zelfde schrijfwijze als QUIET_MODEL, ook
  wegschrijven in `write_gh_files`):
  ```json
  {"priority": [
    {"if": "road_class == PRIMARY", "multiply_by": "0.20"},
    {"else_if": "road_class == SECONDARY", "multiply_by": "0.30"},
    {"else_if": "road_class == TERTIARY", "multiply_by": "0.55"},
    {"else_if": "road_class == RESIDENTIAL", "multiply_by": "0.75"},
    {"if": "surface == ASPHALT || surface == CONCRETE || surface == PAVED", "multiply_by": "0.75"},
    {"if": "road_environment == FERRY", "multiply_by": "0.10"}
  ]}
  ```
  (Netto: paden/tracks/onverhard winnen. Bewust GEEN `!in_popular`-regel —
  de heat-laag is fietsdata.)
- LET OP: encoded values wijzigen = graafherimport nodig. Niets zelf draaien;
  de reviewer doet de herimport. Documenteer het in de README.

## Doorwerking

- `gh.route(..., profile=config.GH_PROFILE)` param; alle aanroepen geven het
  draft-profiel door.
- Draft: veld `"profile"` (default `"quiet"`); `lus draft new --profiel
  quiet|trail`; opnemen in summary.
- Zachte voorkeuren die fietsspecifiek zijn (`avoid_cobbles`, `avoid_concrete`,
  `strict`) blijven werken maar zijn bij trail meestal ongewenst — geen
  validatie nodig, wel een zin in CLAUDE.md.
- MCP: `new_draft` krijgt `profiel="quiet"`-param; `plan_route` krijgt
  `activiteit="fietsen"|"trail"` die op het draft-profiel mapt (toolaantallen
  ongewijzigd).
- CLI `plan-route`: `--activiteit`.

## Tests (puur)

- gh.route body bevat het juiste profiel (router-injectie, bestaande stijl).
- draft.new bewaart profiel; plan_route mapt activiteit → profiel.
- write_gh_files schrijft trail.json en het profiel in config.yml (string-
  assert op de gegenereerde YAML).

## DoD

Tests groen; bestaand gedrag default ongewijzigd (profiel quiet); README/
CLAUDE.md/PRODUCT.md (M5 afvinken, met noot "run/gravel/mtb later als extra
custom models"). Kleine commits; niet pushen; geen docker.
