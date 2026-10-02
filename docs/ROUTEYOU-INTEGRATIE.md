# RouteYou als aanvullende kwaliteitsbron voor Ommeke

Onderzocht op 2 oktober 2026. Dit is een zijtrack naast de reproduceerbare
import van openbare Vlaamse routedata. Er is geen RouteYou-contract,
API-toegang, import of contact met RouteYou uitgevoerd.

## Aanbeveling

RouteYou kan Ommeke vooral verbeteren met **geselecteerde routes, herkomst en
activiteitgebonden kwaliteitslabels**. Dat is waardevol voor de vraag
“welke wegen vormen samen een aangename tocht?”. Het is nog niet aangetoond
dat de verbetering groot is ten opzichte van Toerisme Vlaanderen + OSM.
Eerst de open basis afwerken; vervolgens een beperkte, gelicentieerde proef.

Een grote hoeveelheid willekeurige GPX'en is geen goede reden om de koppeling
te bouwen. Veel routes kunnen dezelfde knooppunten volgen, kopieën zijn of
alleen gepland zijn. Een gepubliceerde route is geen geregistreerde passage.

## Wat is bevestigd en wat nog niet?

RouteYou biedt betaalde webservices voor integratie. Er zijn daarnaast
widgets voor zoeken, weergeven en plannen. Een widgetlicentie bewijst niet
dat we geometrieën mogen opslaan of segmentgewichten mogen afleiden.
[RouteYou-diensten](https://help.routeyou.com/en/topic/view/107/routeyou-services).

RouteYou documenteert een routescore van nul tot vijf sterren. Eén ster staat
voor verificatie; vanaf drie sterren is een route aanbevolen. De beoordeling
omvat meerdere inhoudelijke en functionele criteria. Daarom behandelen we
de score als één signaal en niet als een zuivere meting van landschapskwaliteit
of een toegankelijkheidscertificaat.
[Uitleg routescore](https://support.routeyou.com/hc/en-us/articles/19946435588124-Route-score).

De openbare beschrijving van een content partnership gaat hoofdzakelijk over
content **aanleveren aan RouteYou** en distributie/licentiëring daarvan.
Daaruit volgt niet dat Ommeke automatisch de volledige RouteYou-collectie
mag afnemen. Daarvoor is een afzonderlijke overeenkomst nodig.
[Content partnership](https://help.routeyou.com/en/topic/view/218/content-partnership).

Niet geverifieerd: de precieze afneembare API-velden, Vlaamse dekking per sport,
bulkexport, quota, prijzen, actualiseringsfrequentie, onafhankelijke
segmentbeoordelingen en toestemming voor afgeleide routeplanning.
Er wordt hier geen endpoint of contractvoorwaarde verondersteld.

## Waar kan de meerwaarde groot zijn?

| Gebruik | Verwachte waarde | Voorwaarde |
|---|---|---|
| Recreatieve fiets- en wandelroutes | Goede kans op betere selectie van aantrekkelijke lussen | Curatie voegt iets toe bovenop de bestaande knooppunten |
| Koersfiets, gravel en MTB | Mogelijk sterke verbetering van sportspecifieke voorkeuren | Betrouwbare sportlabels en voldoende actuele routes |
| Thematische wensen: landschap, erfgoed, gezinsuitstap | Mogelijk veel rijkere selectie en uitleg | Gestructureerde labels/POI's beschikbaar én gelicentieerd |
| Buggyvriendelijkheid | Alleen waarde met expliciete, actuele toegankelijkheidsgegevens | Ondergrond, trappen, breedte, doorgangen en hellingen aantoonbaar |
| Hoogtemeters en geen kasseien | Aanvullend; onze weg- en hoogtedata blijven leidend | Geometrie goed gekoppeld aan het onderliggende wegennet |
| Populariteit | Niet aangetoond | Afzonderlijk bewijs van werkelijk gebruik; geen route- of viewtelling als passage |

Een goede route bevat ook gewone verbindingsstukken. We mogen niet elk segment
van een vijfsterrenroute als een vijfsterrensegment behandelen. Een route die
geschikt is voor MTB kan juist ongeschikt zijn voor een buggy of koersfiets.

## Technische aansluiting

De LLM blijft gebruikerswensen structureren. GraphHopper blijft toegang en
routes berekenen; Lusmaker blijft afstand, herhaling en gebruikersvoorwaarden
controleren. RouteYou wordt een vervangbare bronadapter in de datapipeline.

1. **Afgesproken selectie importeren.** Begin bij vertrouwde Vlaamse
   uitgevers en beoordeelde routes. Bewaar bron-ID, uitgever, route-ID,
   activiteit, geometrie, toegestane labels, verificatiedatum en bronlink.
   Houd de oorspronkelijke uitgever apart van het platform.
2. **Snapshots en rechten vastleggen.** Checksums, downloadtijd, bronversie,
   licentie-ID, bewaartermijn en toegestane toepassingen in een manifest.
   Houd deze opslag gescheiden van vrij verspreidbare open-datapacks.
3. **Routes dedupliceren en matchen.** Herken varianten van dezelfde route
   en dezelfde provinciale bron die via meerdere kanalen verschijnt. Koppel
   geometrie op basis van afstand, richting en continuïteit; sla de
   matchzekerheid op. Met alleen nabijheid kun je parallelle paden verwarren.
4. **Kandidaten voorstellen en beoordelen.** Gebruik routes als inspiratie
   voor lussen en geselecteerde corridors. Geef overeenkomende segmenten een
   beperkte, activiteitgebonden bonus. Stel een maximum per onafhankelijke
   bron in; verzadig het effect van extra aanbevelingen.
5. **Beperkingen blijven leidend.** Een hoge score heft een toegangsverbod,
   afstandsgrens of incompatibele ondergrond niet op. Onbekende
   buggygeschiktheid wordt niet positief ingevuld.
6. **Uitleg en intrekking.** Toon de bron van een aanbeveling. Verwerk
   verwijderde routes, ingetrokken rechten en gewijzigde geometrieën; bouw
   afgeleide scores opnieuw. Zonder RouteYou blijft de open routebasis werken.

De huidige `route_sources`-pipeline bewaart al bronfeatures en manifests;
`route_evidence` kan geometrische dekking per sport beoordelen. Een toekomstige
RouteYou-adapter moet een eigen rechtenmodel en deduplicatie toevoegen.
De huidige geometrische matching kent geen GraphHopper-edge-ID's; voor sterke
wegsegmentbonussen is verdere matchingvalidatie nodig.

Geen API-call bij elke gebruikersvraag: synchroniseer vooraf en routeer uit
een lokale versie. Geef de LLM alleen compacte kenmerken en bronverwijzingen.
Foto's en volledige beschrijvingen zijn voor de eerste proef niet nodig.

## Wat moet expliciet in de afspraak staan?

- Commerciële toepassing in Ommeke, inclusief door AI aangestuurde planning.
- Welke uitgevers en routes RouteYou daadwerkelijk mag sublicentiëren.
- Downloaden, lokaal cachen, verwerkingsfrequentie en bewaartermijnen.
- Geometrieën gebruiken om segmentgewichten af te leiden en **nieuwe routes**
  samen te stellen; gebruik van de resulterende GPX-export door eindgebruikers.
- Welke labels en eventuele beoordelingen beschikbaar zijn en hoe ze zijn
  vastgesteld. Routekwaliteit en gebruikersreviews apart houden.
- Verplichte bronvermelding, deeplinks en eventuele weergavebeperkingen.
- Verwijderingen, beëindiging en behandeling van afgeleide scores.
- Kosten voor de pilot en productie; limieten voor bulkdata en updates.
- Gebruik in een open-source engine versus verspreiding van gelicentieerde
  data. De adapter kan open zijn zonder dat het databestand dat is.

Dit is een onderhandelingslijst, geen bevestiging dat RouteYou deze rechten
verleent. Een gewoon consumentenabonnement of GPX-download volstaat niet als
basis voor deze integratie.

## Een proef die de vraag daadwerkelijk beantwoordt

Voorgestelde scope: ongeveer 200–500 gelicentieerde, geselecteerde routes,
verdeeld over enkele Vlaamse regio's en sporten. Dit zijn proefdoelen, geen
vastgestelde aantallen beschikbare RouteYou-routes.

Vergelijk twintig vaste routevragen met dezelfde start, voorkeuren,
afstandsgrenzen en kandidaatseeds. Baseline: actuele open data. Variant:
dezelfde pipeline plus RouteYou. Houd een beoordelingsset apart van de routes
waarmee we bonussen afstellen; splits op uitgever/routefamilie om kopieën in
beide sets te vermijden.

Meet naast de bestaande afstands-, ondergrond- en heen-en-weermetrieken:

- hoeveel onafhankelijk gecureerde informatie RouteYou werkelijk toevoegt;
- of beoordelaars de variant blind aantrekkelijker en passender vinden;
- overtredingen van harde wensen en foutieve toegankelijkheidsclaims;
- kwaliteit van de geometrische matching bij parallelle paden;
- extra omwegen, rekentijd, datakosten en onderhoud.

Voorstel voor een vooraf af te spreken beslisregel: verdergaan wanneer de
variant in minstens 14 van 20 vergelijkingen de voorkeur krijgt, zonder extra
overtredingen van harde wensen, en met aanvaardbare kosten. Dit is een
praktische pilotdrempel, geen statistisch bewijs; daarna volgt terreinreview
en een grotere proef.

Als de data vooral dezelfde knooppunten dupliceren, een goede overeenkomst
ontbreekt of de winst in de proef klein is, houden we RouteYou bij bronlinks
en inspiratie. Gerichte samenwerking met provinciale routebeheerders kan
dan meer waarde leveren.
