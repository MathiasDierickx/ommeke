# Praktijkproef: korte strandwandeling vanaf een hotel in Bredene

Uitgevoerd op 2 oktober 2026. Doel: ongeveer 3 km te voet vanaf de parking naast
ibis Styles Bredene, terug naar de parking, kindvriendelijk en zoveel mogelijk
langs het strand. Eerst de app zelf laten zoeken, daarna helpen met een bron.

## Lokale Codex/MCP-proef na herstel

Op 2 oktober is de volledige keten `lus chat --provider codex` → stdio-MCP →
GraphHopper → GPX/preview uitgevoerd. De lokale proef gebruikt een apart
kustextract uit het aanwezige Belgische OSM-bestand en GraphHopper 11.0 op
poort 18989. De bestaande runtime en `~/.lusmaker` zijn niet gewijzigd.
Na de overstap naar Codex zijn geen Bedrock-aanroepen voor deze proeven gedaan.

Het verbeterde concept `73a3db` geeft 3,0 km en 36 hoogtemeters. Onafhankelijk
uit de GPX-geometrie gemeten: **3,044 km, 126 punten, 0 m sluitingsverschil**.
Start/einde na routersnapping: 51.251404, 2.974101. Er zijn twee geregistreerde
steenwegkruisingen. Dit is een berekende route, geen veiligheidskeuring.

- Hotel: ibis Styles Bredene, Koningin Astridlaan 62; officiële Accor-bron.
- Voorlopige parking: OSM-way 98000850, `access=yes`, `fee=yes`, vlak bij het hotel.
  Het kaartcentrum is geen bevestigde ingang; de bedoelde parking is niet met
  de gebruiker bevestigd.
- Strandanker: OSM-way 72890837. Actuele strandtoegang, veilige oversteek,
  kindvriendelijkheid en maximale strandlengte blijven onbevestigd.
- Bestanden: `.route-data/bredene-codex/exports/73a3db/route.gpx` en `preview.html`.
- Gesprekslog: `.route-data/bredene-codex/conversations/b9204b20-12a3-4692-9bbb-01bdc09f6a1b.json`.

De proef vond en corrigeerde vier problemen: regio-onafhankelijke area-probes,
onterechte vragen naar klimgewichten bij een gewone wandeling, niet meegerekende
aanloopafstand naar het strand en onvoldoende rondritkandidaten bij korte lussen.
De normale vijf kandidaten blijven het eerste pad; alleen bij mislukking met een
afstandsdoel worden maximaal vijftien extra kandidaten geprobeerd. De drie
bestaande routeregressiecassettes blijven ongewijzigd groen.

De eerste release `08a39da` is succesvol naar AWS en Vercel uitgerold, inclusief
CI en publieke smoke-tests. De correcties aan de korte-lusoptimalisatie volgen
in de vervolguitrol. Persoonlijke Codex-authenticatie is niet naar AWS gekopieerd;
de online chatprovider is niet gewijzigd door deze lokale providerkeuze.

## Eindproef met de oorspronkelijke prompt, zonder technische vervolgvragen

Nieuw gesprek `fca7a426-d734-4558-8744-2355cd6d0cb4`, Codex-provider,
werkmap `.route-data/bredene-offline-places`: de oorspronkelijke prompt levert
zelfstandig route `d1fc6a` op. Hotelzoekopdracht en lokale OSM-kandidaten werken;
voor parking en strand zijn geen Overpass-aanroepen nodig. Een mislukte
strandnaam wordt door de agent hersteld met de gevonden strandcoördinaten.

Uitkomst: **3,0 km / +36 m**; onafhankelijk uit GPX **3,043 km, 125 punten,
0 m sluitingsverschil**. Start en einde: 51.251401, 2.974091. Dezelfde
beperkingen over parkingingang, toegang, kruisingen en kindvriendelijkheid gelden.
GPX en preview zijn op verzoek ook naar Downloads gekopieerd.
Alle 275 offline tests zijn groen, inclusief ongewijzigde routeregressiecassettes.

Deze eenmalig voorbereide lokale kustomgeving is te hergebruiken zolang de
aparte GraphHopper op poort 18989 draait:

```sh
LUSMAKER_HOME="$PWD/.route-data/coast-home" .venv/bin/lus chat \
  'Een wandeling van ongeveer 3 km vanaf de parking bij ibis Styles Bredene, langs het strand en terug' \
  --provider codex --workspace .route-data/bredene-offline-places \
  --gh-url http://127.0.0.1:18989
```

Een code-deployment ververst geen bestaande regiopacks. De nieuwe lokale
plaatsindex komt pas in een online regiopack na opnieuw bouwen. Een geslaagde
lokale Codex-proef is daarom geen bewijs van dezelfde uitkomst via de bestaande
online Bedrock-provider en het bestaande online pack.

## Eerste webproef (vóór de fixes)

De webapp maakte een concept “Strandwandeling Bredene · 3 km” van 0,0 km aan.
Er verscheen geen assistentantwoord, ook niet na herladen van het gesprek.
De browser meldde een TypeError bij het verwerken van een ontbrekend message.id.
Een tweede bericht met hoteladres en coördinaten leverde evenmin een zichtbaar
assistentaantwoord of geverifieerde wandeling op. De precieze serveroorzaak is
nog niet vastgesteld; toegang tot de logs van het deploymentaccount ontbreekt.

De lokale CLI accepteert gestructureerde argumenten, geen vrije-tekstprompt.
De ondersteunde delen zijn handmatig vertaald en in tijdelijke opslag getest:

```sh
lus plan-route --start 'ibis Styles Bredene' --activiteit trail \
  --target-km 3 --tolerance-km 0.3 --doel toeren --autovrij \
  --naam 'Strandwandeling Bredene · 3 km'
```

Resultaat: exit 1, hotel niet gevonden. `lus geocode 'ibis Styles Bredene'`
gaf nul resultaten. De bestaande lokale GraphHopper op poort 8989 was ook
buiten de sandbox niet bereikbaar. Er is geen runtime gestart of gewijzigd.

De lokale Vlaanderen-configuratie heeft bbox 50.68,3.35,51.10,4.20; de
hotelcoördinaat 51.25097,2.97303 valt daarbuiten. Dit zegt iets over de lokale
regioconfiguratie, niet over een onafhankelijk gecontroleerde productiegraph.

## Gecontroleerde bron en onzekerheden

[Accor](https://all.accor.com/hotel/B7Q2/index.en.shtml) vermeldt Koningin
Astridlaan 62, 8450 Bredene, GPS 51.25097,2.97303 en openbare buitenparking nabij
het hotel. Dit is de hotellocatie, geen exacte parkinguitgang of strandopgang.
Er is geen 3 km-geometrie, maximale strandfractie of kindvriendelijkheid bewezen.
`trail` gebruikt voettoegang; dit is geen afzonderlijke kindveiligheidscontrole.
`langs_water` ondersteunt benoemde waterlopen, geen strandoptimalisatie.

## Verbeteringen uit deze proef

- Onvolledige chatresponses geven een herstelmelding in plaats van een rendercrash.
- Nulafstand en ongeldige afstanden zijn geen downloadbare, voltooide routes.
- Concepten blijven in het gesprek; alleen expliciet klaar gemelde routes worden
  automatisch geopend. Bestaande route_ids blijven behouden voor compatibiliteit.
- De iteratielimiet noemt een needs_input-concept niet meer “klaar”.
- “Nieuwe route” opent expliciet het invoerscherm, zonder terug te springen naar
  de laatst geopende route bij een opnieuw geladen pagina-module.
- Modelinstructies onderscheiden een voetgangersprofiel van geverifieerde
  kindvriendelijkheid en verbieden het verzinnen van hotel- of parkinginformatie.

Nog nodig voor succesvolle acceptatie: beschikbare kustdata/router, betrouwbare
startpuntzoeker met parking-/toegangsonzekerheid, expliciete kustvoorkeur en
controle van veilige oversteken. Geen fictieve GPX als vervanging gemaakt.
