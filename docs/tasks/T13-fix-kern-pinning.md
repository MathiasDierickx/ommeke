# T13 — Fix: alleen de klimkern pinnen, kruispunt-uiteinden als aansluitpunten

## Regressie (gevonden na T10, prioriteit hoog)

Na T10 (klim-uiteinden verlengd tot kruispunten) is de heen-en-weer-score van
trail-composities verslechterd: verse `optimize` Spoorweglaan/trail/10 km
ging van ~200 m naar 993 m retrace; `berendries_quiet`-cassette van 293 →
434 m. Oorzaak (hypothese, verifieer): `draft._waypoints` pint de klim-leg op
de VOLLEDIGE `geom` — die nu ook de vlakke verlengtails bevat. Aanrijroutes
worden daardoor om/over de tails gedwongen, met extra pendel.

## Fix

1. Klimrecords krijgen naast `geom` (verlengd) ook de kerngrenzen:
   `kern_van`/`kern_tot` als indices in `geom` (climbs.py zet die al bij het
   verlengen — zo niet, voeg toe; `kern_m` bestaat al).
2. `draft._waypoints`: foot/top blijven de VERLENGDE uiteinden (kruispunten —
   dat is de winst van T10), maar de via-pinning gebruikt alleen de KERN
   (resample van `geom[kern_van:kern_tot+1]` per 150 m) plus de twee
   uiteinden. De tails krijgen dus geen gedwongen via-punten; GH mag er vrij
   naartoe routeren.
3. De klim-corridorzones (anti-retrace voor connectors) blijven op de
   volledige geom.
4. Herbereken niets aan de klim-DB zelf behalve eventueel de indices
   (reviewer draait `lus climbs detect` + `lus climbs resolve` en daarna de
   cassette-herrecord; verwachting: heen-en-weer terug richting pre-T10 of
   beter — rapporteer de tabel).

## Acceptatie (door reviewer, live)

- verse optimize Spoorweglaan/trail/10km/hm: heen_en_weer < 300 m
- berendries_quiet-cassette: heen_en_weer ≤ 300 m (scherp de invariant weer
  aan naar < 400 zodra dat haalbaar blijkt)

## Tests (puur)

- _waypoints: synthetische klim met tails → via-punten liggen alleen op de
  kern + uiteinden; zonder kern-indices (oude records) → gedrag zoals nu
  (fallback volledige geom, geen crash).

## DoD

Suite groen; kleine commits; niet pushen. NIET tegelijk met een andere taak
in draft.py werken.
