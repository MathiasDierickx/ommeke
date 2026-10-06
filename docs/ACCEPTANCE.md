# Praktijkproeven en componentcontrole

Stand: 2 oktober 2026. De runtime is niet gewijzigd. Onderstaande routes zijn
herhalingen van opgeslagen echte GraphHopper-antwoorden, geen nieuwe live ritten.

| Vraag / cassette | Afstand geometrie | Hoogtemeters | Hergebruik | Resultaat |
|---|---:|---:|---:|---|
| Rustige fietslus via Berendries (`berendries_quiet`) | 59,576 km | 744 m | 434 m | gesloten, geen onderbreking |
| Korte onverharde trail (`trail_offroad`) | 8,485 km | 90 m | 0 m | 51% onverhard, gesloten |
| Fietslus met vermijdzone Zottegem (`zottegem_avoid`) | 64,749 km | 762 m | 534 m | 35 m marge buiten vermijdzone |

De vaste cassettegrenzen staan in `tests/test_regression.py`. Dezelfde drie
cassettes lopen ook door `quality.evaluate` met afstandsband, lusstatus,
vermijdzone uit het draft en een overlapgrens. Voor overlap geldt standaard
650 m: dit ligt boven de gemeten cassettewaarde (maximaal 534 m) met marge;
de grens is per evaluatie instelbaar via `overlap_tolerance_m` en verschijnt
als `overlap_m` en `overlap_tolerance_m` in de metrics. Een cassette die een
echte afstandsgrens niet haalt, blijft rood; de band wordt niet op basis van
een mislukking verruimd. Hergebruik is
hier gemeten en begrensd, niet volledig opgelost. Een gesloten geometrie bewijst
geen actuele toegankelijkheid, verkeersveiligheid of aangename rit.

## Offline acceptatiematrix (issue #4)

De regressierijen gebruiken de bestaande cassettegeometrie. Synthetische rijen
gebruiken vaste geometrie of een geïnjecteerde router; er zijn geen nieuwe
opnames of netwerkcalls. `tests/test_acceptance.py` borgt dat alle genoemde
scenariofuncties blijven bestaan.

| Scenario | Metriek | Tolerantie / grens | Uitkomst |
|---|---|---|---|
| `berendries_quiet` (cassette) | afstand, sluiting, onderbreking, overlap, vermijdzone | 54–64 km; lus 25 m; legs 25 m; overlap 650 m; vermijdzone 200 m | routekwaliteit moet slagen; bestaande invarianten blijven gelden |
| `trail_offroad` (cassette) | afstand, sluiting, overlap | 6–9 km; lus 25 m; legs 25 m; overlap 650 m | routekwaliteit en trail-invarianten slagen |
| `zottegem_avoid` (cassette) | afstand, sluiting, overlap, marge tot Zottegem | max 70 km; lus 25 m; legs 25 m; overlap 650 m; marge ≥ −200 m | routekwaliteit en vermijd-invariant slagen |
| fiets vs trail (synthetisch) | profiel/activiteit | fiets `quiet`; trail `trail` | profielen blijven onderscheiden |
| hard maximum vs zacht doel (synthetisch) | afstandsstatus en waarschuwing | hard max 10 km; zacht doel tolerantie 1 km | 12 km hard wordt afgewezen; zacht doel wordt niet als hard maximum gemeld |
| waterloop en landmark (synthetisch) | aandeel nabij water; dichtstbijzijnde afstand anker | water ≥ 10%; anker ≤ 30 m | beide geometrische voorwaarden slagen |
| vermijdzone (synthetisch) | marge tot zone | tolerantie 0 m | route door de zone faalt en rapporteert negatieve marge |
| onhaalbare wens (synthetisch, router geïnjecteerd) | harde afstand | max 5 km, routerantwoord 20 km | Nederlandse `IntentError` meldt overschrijding; geen stille acceptatie |
| heen-en-weer (synthetisch) | overlap | configureerbaar, hier 10 m | teruggereden segment faalt en grens wordt gerapporteerd |

De cassettegrenzen komen uit de eerder vastgelegde praktijkbanden in deze
file (`54–64`, `6–9`, `max 70 km`). De huidige geometrie wordt direct aan die
voorwaarden getoetst; een eventuele mislukking wordt als cassette-afwijking
gerapporteerd en niet opgelost door de tolerantie automatisch te verruimen.

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

## Productieproeven van 2 oktober, avond

Op expliciete opdracht zijn GitHub/AWS/Vercel-uitrollen en browserproeven nu
wel uitgevoerd, in de persoonlijke Chrome van de eigenaar. De historische
reviewer-only-paragraaf hierboven beschrijft de eerdere offline iteratie.

- AWS-run `37054008559`: uitbreiding met snelplanner, terugweg, FIT en POI's.
- AWS-run `37054942458`: eerste SSE-implementatie. Live proef vond een race
  tussen de POST-body en de disconnectlistener; dus geen geslaagde E2E-acceptatie.
- Reparatie `171fdd8`: body lezen vóór starten van StreamingResponse; een nieuwe
  test borgt het eenmalig lezen vóór de response. De herhaalde browserproef
  toont nu echte voortgang vóór afronding, onder meer de ondergrondcontrole.
- De snelplanner miste aanvankelijk `profiel_naam=standaard`. Reparatie
  `70b30de` wordt gedekt door een test die de echte intentielaag doorloopt.
- Een bestaande 50-km-route opent met kaart, hoogteprofiel en routekwaliteit.
  GPX en FIT zijn via de echte downloadknoppen in Chrome opgehaald. GPX:
  1.237 trackpunten, 80.880 bytes. FIT: 49.667 bytes, `.FIT`-header en geldige
  bestands-CRC. Dit is geen Garmin-toestelacceptatie.

De SSE-client test gesplitste UTF-8, CRLF op chunkgrenzen, heartbeats, terminale
fouten en een verbroken stream zonder resultaat. Geen test stuurt een echte
netwerkcall vanuit de offline suite. Totaal: 295 Python-tests en 9 Node-tests.

Herhaalde snelplannerproef, productie-route `ca3e8a`: gevraagd 40 km vanuit
Wetteren, fiets/toeren. Resultaat 39,320 km uit 1.007 GPX-trackpunten, sluiting
0,00 m, 199 GPX-routepunten met navigatiecues. Nieuw FIT-bestand 61.561 bytes
met geldige CRC. Chrome toonde achtereenvolgens de ondergrondcontrole en
lusvariant 2 vóór het eindresultaat. De routekaart toont 39,3 km / 416 m.
Offline bewaren en de afzonderlijke routeshell tonen de bewaarde revisie,
routelijn en hoogteprofiel; vliegtuigmodus en GPS-ontvangst zijn niet bewezen.
Backend-herstelrun `37055797218` en frontend-CI `37056666279` zijn geslaagd;
Vercel meldt success voor `c04c35a`.

Chatproef: “Maak een rustige fietsroute van ongeveer 20 km vanuit Wetteren.
Kasseien en beton zijn oké, vermijd drukke wegen waar mogelijk. Noem deze route
E2E voortgang Wetteren.” Resultaat route `1f159f`, in de app 19,9 km / 237 m.
Gedownloade GPX: 547 punten, geodetisch 19,847 km, sluiting 0 m, 104 cues.
CloudWatch meet 61,716 s voor `/api/conversations/:id/messages/stream`.
Het antwoord bleef in het gesprek; de routeknop opende de bijbehorende kaart.
De geautomatiseerde routeberekening blijft dus te traag voor het 15-s-doel van #19.

Foutproef: snelplanner met start `91,3` toont een begrijpelijke
coördinatenfout en de knop “Nieuwe poging voorbereiden”; spinner stopt.
Desktopcontrole op 1512 × 767: geen horizontale overflow op route- en
offlinepagina. Deze ronde bewijst geen nieuwe mobiele, Garmin- of GPS-acceptatie.
