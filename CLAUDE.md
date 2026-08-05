# Lusmaker — instructies voor Claude

Lusmaker bouwt fiets-GPX-lussen (Vlaamse Ardennen) stap voor stap via de `lus`-CLI.
Jij bent de conversatielaag: vertaal wensen van de gebruiker ("mooie lus naar de
Berendries, rustige wegen, geen twee keer dezelfde baan") naar CLI-stappen, en
speel vragen/suggesties van de tool terug naar de gebruiker.

## Aanroepen

```bash
.venv/bin/lus <command>     # vanuit de repo-root
```

Alle output is JSON. Fouten komen als `{"error": "..."}` met exit code 1.
GraphHopper moet draaien: `docker compose up -d` (check met `lus status`).

## Typische flow

1. `lus draft new --start "Wetteren" --name berendries-lus` — start een lus-draft.
   Check `start_geocoded_als` in de output; bij twijfel de kandidaten aan de
   gebruiker voorleggen. Adres kan ook: `--start "Stationsstraat, Wetteren"`.
2. `lus climbs near Wetteren --radius-km 25` of `lus climbs list` — kies klimmen.
3. `lus draft add-climb <id> berendries` — voeg de doelklim toe.
4. `lus draft route <id>` — routeer. De lus vermijdt automatisch de eigen
   heenweg (corridor-penalty), klimmen worden voet→top gereden.
5. `lus draft suggest <id> --max-detour-km 10` — extra klimmen die weinig omweg
   vragen. **Stel deze voor aan de gebruiker** ("wil je de Molenberg erbij voor
   ~X km extra?"); elk voorstel bevat het exacte add-climb-commando.
6. Herhaal 3–5 tot de gebruiker tevreden is, dan `lus draft export <id> -o naam.gpx`.

## Weetjes

- Klim-ids: zie `lus climbs list` (bv. `berendries`, `molenberg`, `oude-kwaremont`).
- Volgorde van klimmen = volgorde in `draft.climbs`; `--at N` voegt op positie N in.
- `suggest` geeft `invoegen_op_positie` — gebruik die in het add-climb-commando.
- Na add/remove-climb is de route stale; altijd opnieuw `draft route` draaien.
- `draft route` en `suggest` doen meerdere GraphHopper-calls en kunnen enkele
  seconden duren.
- Regio is beperkt tot de bbox Wetteren/Vlaamse Ardennen (config.BBOX). Punten
  daarbuiten geocoden niet.
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
