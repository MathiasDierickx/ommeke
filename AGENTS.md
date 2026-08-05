# Lusmaker — instructies voor code-agents (Codex)

Je werkt aan Lusmaker: een CLI (straks MCP-server) die fiets-GPX-lussen bouwt
bovenop een lokale GraphHopper. Lees `PRODUCT.md` voor de richting en
`README.md` voor de architectuur. Taakbriefs staan in `docs/tasks/`.

## Harde regels

1. **Raak de runtime niet aan.** Geen `docker`-commando's, geen bestanden in
   `~/.lusmaker` verwijderen of herschrijven, GraphHopper niet herstarten.
   De reviewer draait zelf de live smoke-tests.
2. **Geen netwerk-calls in tests.** Unit-tests testen pure logica; alles wat
   GraphHopper of het web nodig heeft, wordt handmatig gereviewd. Als een
   functie router-calls doet, maak de router injecteerbaar (parameter met
   default) in plaats van te mocken via patching van module-globals.
3. **CLI-contract**: elk commando print JSON (`ensure_ascii=False, indent=2`);
   fouten als `{"error": "..."}` met exit code 1. Gebruikersgerichte strings
   in het Nederlands, code/identifiers in het Engels of bestaand Nederlands
   idioom van de module volgen.
4. **Geen nieuwe dependencies** zonder expliciete opdracht in de taakbrief.
   Python ≥3.11, huidige deps: osmium, numpy, PyYAML.
5. Bestaande commando's en hun outputvelden niet breken; alleen toevoegen.
6. Kleine, gerichte commits met heldere messages. Niet pushen.

## Werkwijze

- Venv: `.venv/bin/python`, CLI: `.venv/bin/lus`.
- Tests: `tests/` met pytest-stijl zonder pytest-dependency — draaibaar via
  `.venv/bin/python -m tests.run` (maak dat runnertje als het nog niet
  bestaat: importeer test_*-modules en draai functies die met `test_` starten;
  faal met exit 1 en een duidelijke traceback).
- Na elke wijziging: `.venv/bin/lus --help` moet werken en
  `.venv/bin/python -m tests.run` moet groen zijn.
- Module-overzicht: `cli.py` (argparse, dun), `draft.py` (state + route +
  suggest), `gh.py` (GraphHopper-client), `climbs.py` (klim-DB + detectie),
  `heat.py` (populariteitslaag), `analysis.py` (kwaliteitsmetrieken),
  `geo.py` (geometrie), `osm.py`/`geocode.py` (extract + geocoder),
  `gh_config.py`/`config.py` (configuratie), `gpx.py` (export).
