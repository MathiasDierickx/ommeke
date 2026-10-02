# Praktijkproeven en componentcontrole

Stand: 2 oktober 2026. De runtime is niet gewijzigd. Onderstaande routes zijn
herhalingen van opgeslagen echte GraphHopper-antwoorden, geen nieuwe live ritten.

| Vraag / cassette | Afstand geometrie | Hoogtemeters | Hergebruik | Resultaat |
|---|---:|---:|---:|---|
| Rustige fietslus via Berendries (`berendries_quiet`) | 59,576 km | 744 m | 434 m | gesloten, geen onderbreking |
| Korte onverharde trail (`trail_offroad`) | 8,485 km | 90 m | 0 m | 51% onverhard, gesloten |
| Fietslus met vermijdzone Zottegem (`zottegem_avoid`) | 64,749 km | 762 m | 534 m | 35 m marge buiten vermijdzone |

De vaste cassettegrenzen staan in `tests/test_regression.py`. Hergebruik is
hier gemeten en begrensd, niet volledig opgelost. Een gesloten geometrie bewijst
geen actuele toegankelijkheid, verkeersveiligheid of aangename rit.

Vier nieuwe acceptatietests faalden vóór de verbeteringen en slagen nu:

- Een korte lus die na opvulling 12 km wordt bij een hard maximum van 10 km:
  het resultaat wordt geweigerd en de ongeldige berekening wordt gewist.
- Een zachte doelafstand: geen onterechte waarschuwing over een harde grens.
- NaN, oneindig en booleans als afstand: afwijzen vóór routing.
- Gevraagde waterloop zonder beschikbare data: expliciet onvervulde wens melden.

Daarnaast controleert pure geometrie de sluiting (25 m), aansluiting tussen
legs (25 m), afstand, ankers, doorsnijding van vermijdzones en nabijheid van
water. De geometrieproeven zijn synthetisch; er is nog geen echte waterloop-
of landmarkcassette bijgemaakt.

## Zelf herhalen

```sh
.venv/bin/lus check list
.venv/bin/lus check scenarios
.venv/bin/lus check engine
.venv/bin/lus check api
.venv/bin/lus check mcp
.venv/bin/lus check all
.venv/bin/lus check web
```

`all` draait de volledige Python-suite; `web` draait apart TypeScript,
Node-unit-tests en een productiebuild. `infra` test de Python-deployhelpers;
Terraform apart: `terraform -chdir=infra/terraform validate`.
Alle Python-unit-tests blokkeren sockettoegang. De componentrunner gebruikt een
tijdelijke LUSMAKER_HOME en verwijdert cloudcredentials uit de procesomgeving.
CLI-rapporten zijn JSON; mislukte controles geven exitcode 1. Na installatie is
ook `lus-check` beschikbaar. Zonder installatie werkt `python -m lusmaker.checks`.

Voor eigen opgeslagen drafts (met `_geometry`) en voorwaarden:

```sh
.venv/bin/lus check quality --input draft.json --constraints constraints.json
```

Zie `lusmaker/quality.py` voor de voorwaarden en `tests/test_quality.py` voor
uitvoerbare voorbeelden. `scenarios` bundelt tien concrete scenario's.

## Mobiele interface

Start `cd web && npm run qa`; open `http://127.0.0.1:3017/qa-local`.
Deze lokale fixture gebruikt de echte route- en navigatiecomponenten met
fictieve gegevens en geïnjecteerde acties. Ze is onbeschikbaar in productie.
Handmatig gecontroleerd op desktop en 390 × 844: +5 km, delen/intrekken,
feedback, revisieconflict en navigatie openen/sluiten. Geen horizontale overflow.
Een browserextensie veroorzaakte een hydrationwaarschuwing; daarom claimen we
geen foutloze console. Login, echte GPX-download en backend blijven live checks.

## Live acceptatie door de reviewer

Niet door de code-agent uitgevoerd (AGENTS.md). Probeer met de actuele engine:

1. “Fietslus vanuit Wetteren via Berendries, rustige wegen, maximaal 65 km.”
2. “Trail vanuit Blaarmeersen, ongeveer 8 km, zoveel mogelijk onverhard.”
3. “Lus vanuit Wetteren, ongeveer 40 km, langs de Schelde.”
4. “Fietslus vanuit Zottegem, maximaal 45 km, vermijd het centrum.”
5. “Lus van maximaal 5 km via een anker 20 km verderop.” Verwacht uitleg of
   afwijzing, nooit een stilzwijgend overschreden hard maximum.

Bewaar vraag, engine-/packversie, route-JSON, GPX, wachttijd, constraint_report
en handmatige bruikbaarheidsbeoordeling. Gebruik voor water en ankers echte
lokale coördinaten. Leg afwijkingen vast op issue #4. Cassette-opname en live
smoke blijven expliciete reviewerhandelingen; ze horen niet in offline CI.
