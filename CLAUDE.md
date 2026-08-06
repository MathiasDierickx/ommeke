# Lusmaker — instructies voor Claude

Lusmaker bouwt fiets-GPX-lussen (Vlaamse Ardennen) stap voor stap via de `lus`-CLI.
Jij bent de conversatielaag: vertaal wensen van de gebruiker ("mooie lus naar de
Berendries, rustige wegen, geen twee keer dezelfde baan") naar CLI-stappen, en
speel vragen/suggesties van de tool terug naar de gebruiker.
Dezelfde flow is ook beschikbaar via de stdio MCP-server `lus-mcp`.

## Begin met de composiet-tools

Gebruik via MCP eerst `plan_route`: die maakt de draft, verwerkt klimmen en
vermijdplaatsen, routeert of optimaliseert, en levert meteen GPX plus preview.
Gebruik daarna `adjust_route` om meerdere wijzigingen in één call toe te
passen. Grijp alleen naar `new_draft`, `add_climb`, `avoid_place`,
`route_draft`, `export_gpx` en de andere granulaire tools als de composiet-flow
een uitzonderlijke handeling niet kan uitdrukken.

Dit beperkt de drie hosted kostenposten tegelijk: minder round-trips die de
gesprekscontext opnieuw meesturen, kleinere resultaten zonder geometrie en
legs, en minder toolschema's in de systeemprompt. `route_details` geeft legs en
de volledige kwaliteitsmetrieken alleen wanneer de gebruiker ernaar vraagt.

## Aanroepen

```bash
.venv/bin/lus <command>     # vanuit de repo-root
```

Alle output is JSON. Fouten komen als `{"error": "..."}` met exit code 1.
GraphHopper moet draaien: `docker compose up -d` (check met `lus status`).

## Typische flow

Via MCP vervangt één `plan_route(...)` normaal stappen 1 t/m 6 en de export;
een latere `adjust_route(...)` bundelt alle gevraagde wijzigingen. De
onderstaande granulaire flow blijft beschikbaar als uitwijkmogelijkheid en
voor CLI-gebruik.

0. Als de plaats niet lokaal geocodet kan worden of geen passende regio
   beschikbaar is: roep `ensure_region(place)` aan (CLI:
   `lus region ensure "<plaats>"`). **Meld de gebruiker meteen dat het
   klaarzetten bij een cache-miss minuten kan duren en blokkeer het gesprek
   niet.** Poll later `region_status(slug)` / `lus region status <slug>`.
   Ga pas bij fase `klaar` verder met `new_draft(..., region=slug)`. Bij
   `status: fout` toon je `melding` en probeer je niet blind verder.
1. `lus draft new --start "Wetteren" --name berendries-lus` — start een lus-draft.
   Check `start_geocoded_als` in de output; bij twijfel de kandidaten aan de
   gebruiker voorleggen. Adres kan ook: `--start "Stationsstraat, Wetteren"`.
2. `lus climbs near Wetteren --radius-km 25` of `lus climbs list` — kies klimmen.
3. `lus draft add-climb <id> berendries` — voeg de doelklim toe.
4. `lus draft route <id>` — routeer. De lus vermijdt automatisch de eigen
   heenweg (corridor-penalty), klimmen worden voet→top gereden.
5. Bied na `route` altijd een kaartpreview aan:
   `lus draft preview <id>`. Geef het teruggekomen `file`-pad aan de gebruiker,
   zodat die de route, klimmen en het hoogteprofiel kan openen en controleren.
6. Bij een afstandsbudget: `lus draft optimize <id> --max-km 45` — vult de lus
   automatisch aan met klimmen en bewaakt het harde budget na elke herroutering.
   Gebruik `--objective hm-per-km` als efficiënt klimmen belangrijker is dan
   het absolute aantal hoogtemeters. Zonder initiële klim kiest de optimizer
   zelf een bereikbaar anker voor een lus.
   Bied na `optimize` opnieuw een preview aan van het definitieve resultaat.
7. Voor handmatige keuze: `lus draft suggest <id> --max-detour-km 10` — extra
   klimmen die weinig omweg vragen. **Stel deze voor aan de gebruiker** ("wil je
   de Molenberg erbij voor ~X km extra?"); elk voorstel bevat het exacte
   add-climb-commando.
8. Exporteer wanneer de gebruiker tevreden is:
   `lus draft export <id> -o naam.gpx`.

## Taalgestuurde voorkeuren -> tool calls

| Gebruiker zegt | Commando |
|---|---|
| "vermijd Zottegem" / "liever niet door X" | `lus draft avoid <id> "X" [--radius-km 2.5] [--factor 0.35]` |
| "geen kasseien" / "liever asfalt" | `--vermijd-kasseien` bij `draft new` |
| "betonbanen bollen slecht" | `--vermijd-beton` bij `draft new` |
| "zo weinig mogelijk steenwegen" (hard) | `--strict` bij `draft new` |
| "rij graag waar veel gefietst wordt" | `lus heat build` na GPX-drop (zie hieronder) |
| "maximaal 45 km, zoveel mogelijk klimmen" | `lus draft optimize <id> --max-km 45 --objective hm` |
| "efficiënt klimmen binnen 45 km" | `lus draft optimize <id> --max-km 45 --objective hm-per-km` |

Dit zijn zachte voorkeuren (penalties, geen verboden) — kort meerijden op een
steenweg kan dus nog. Check het effect in `computed.kwaliteit`
(kassei_m, steenweg_m, steenweg_kruisingen) en koppel terug naar de gebruiker.

## Persoonlijke heatmap (populaire wegen)

De gebruiker kan eigen ritten (Strava/Garmin-export, toertocht-GPX) in
`~/.lusmaker/heat/` droppen. Dan: `lus heat build`, gevolgd door
`rm -rf ~/.lusmaker/gh/graph-cache && docker compose restart graphhopper`
(herimport ~5 min). Daarna krijgen bereden corridors een relatieve boost in
alle routing, en rapporteert `computed.kwaliteit.populair_pct` hoeveel van de
route op bekende wegen ligt. `lus heat status` toont wat actief is.
De Strava Global Heatmap zelf mag juridisch niet gebruikt worden; dit is de
legale variant met eigen data.

## Weetjes

- Klim-ids: zie `lus climbs list` (bv. `berendries`, `molenberg`, `oude-kwaremont`).
- Naast de bekende klimmen zijn er ~700 auto-gedetecteerde (`auto-*`, uit een
  DEM-sweep over alle wegen; `lus climbs detect` om te verversen). Ze doen
  gewoon mee in `suggest` en `climbs near` — zo mis je geen onbekende
  hellingen zoals de Diepestraat.
- `suggest`-schattingen zijn corridor-vrij; na toevoegen kan de werkelijke
  meerprijs ~1-2 km hoger uitvallen. `optimize` vangt dit automatisch op met
  een veiligheidsmarge en rollback; bij handmatig toevoegen moet je zelf
  herrouteren en het echte totaal melden.
- Volgorde van klimmen = volgorde in `draft.climbs`; `--at N` voegt op positie N in.
- `suggest` geeft `invoegen_op_positie` — gebruik die in het add-climb-commando.
- Na add/remove-climb is de route stale; altijd opnieuw `draft route` draaien.
- `draft route`, `suggest` en `optimize` doen meerdere GraphHopper-calls en
  kunnen enkele seconden duren.
- Regiopacks hebben elk hun eigen bbox, caches en GraphHopper. Gebruik
  `lus region list`; nieuwe drafts kunnen `--region <slug>` krijgen en bewaren
  die regio voor alle vervolgstappen. Zonder register blijft Vlaanderen
  legacy-default.
- Voor een onbekende plaats: `ensure_region` → wachttijd melden →
  `region_status` pollen → pas na `klaar` `new_draft` met de teruggegeven regio.
  Provisioning draait in een apart proces; houd geen tool-call open terwijl
  GraphHopper importeert.
- Nieuwe klimmen toevoegen: kopieer `lusmaker/climbs.yaml` naar
  `~/.lusmaker/climbs.yaml`, vul aan, en draai `lus climbs resolve`.

## Setup vanaf nul (eenmalig)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
.venv/bin/lus setup      # downloads (~700 MB) + GraphHopper-config
docker compose up -d     # GraphHopper importeert België (~5-15 min, eenmalig)
.venv/bin/lus build      # klim-database + geocoder (~2-4 min, eenmalig)
.venv/bin/lus status     # alles ok?
```
