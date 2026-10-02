# Praktijkproef: korte strandwandeling vanaf een hotel in Bredene

Uitgevoerd op 2 oktober 2026. Doel: ongeveer 3 km te voet vanaf de parking naast
ibis Styles Bredene, terug naar de parking, kindvriendelijk en zoveel mogelijk
langs het strand. Eerst de app zelf laten zoeken, daarna helpen met een bron.

## Werkelijke uitkomst

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
