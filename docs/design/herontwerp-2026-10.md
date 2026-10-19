# Herontwerp Ommeke: één gesprek, drie schermen

Concept van 19 oktober 2026. Opdracht van Mathias: de app volledig herdenken
zodat een kind hem snapt, los van de eerste use case (klimmen toevoegen,
kasseien vermijden), met een taalmodel dat zelf vraagt wat je zoekt en daaruit
een scoresysteem op maat bouwt.

Status: voorstel. Geen code gewijzigd. Uitvoering kan in slices (onderaan).
Randvoorwaarde: 100 % serverless, geen warme GraphHopper.

## 1. Waarom de huidige app niet "kinderlijk eenvoudig" is

Vastgesteld in productie op 19 oktober (persoonlijke Chrome, ingelogd):

- **Twee ingangen tegelijk.** Het startscherm toont een formulier met acht
  activiteitsknoppen, drie doelknoppen én een chatbalk. De gebruiker moet
  kiezen hoe hij begint voor hij weet wat hij wil.
- **Sidebar eerst.** Gesprekken en bibliotheek staan links; op mobiel zit dat
  achter een hamburger. Een nieuwe gebruiker heeft niets om te tonen.
- **Routepagina is een atelier.** Na het resultaat zie je "Routeatelier:
  Aanpassen", −5 km/+5 km, doelknoppen Klimmen/Offroad/Toeren/Kort, "Klim
  toevoegen", "Plaats vermijden". Dat is het vocabulaire van de koersfietser,
  niet van de wandelaar met kinderen.
- **Vaste voorkeurenlijst.** Het profiel kent vijf gewichten (hoogtemeters,
  offroad, populair, autovrij, kort) en acht ja/nee-voorkeuren. De situationele
  vragen zijn vijf hardgecodeerde rijen (`questions.py`). Alles wat daarbuiten
  valt ("rustig voor mijn hond", "zo veel mogelijk schaduw", "geen trappen",
  "licht onderweg want het wordt donker") kan het model alleen in tekst
  beloven, niet meten of sturen.
- **Kwaliteit zonder uitleg.** De route toont km en hoogtemeters. Waarom dit
  déze route is, wat er gemeten is en wat niet gelukt is, blijft onzichtbaar.
- **Onafgemaakte concepten.** Een routeconcept dat op antwoorden wacht toont
  "Nog geen kaart voor deze route" en uitgegrijsde downloadknoppen. Een kind
  denkt: kapot.

## 2. Principe

> **Lus vraagt, jij tikt.** Eén gesprek dat begint met wat je gaat doen en
> eindigt met een kaart die uitlegt waarom.

Drie schermen, geen menu's:

| Scherm | Vraag die het beantwoordt | Wat je er doet |
|---|---|---|
| **Start** | Wat ga je doen, waar, hoe lang? | drie tikken |
| **Gesprek** | Wat telt voor jou vandaag? | vragen beantwoorden met knoppen of tekst |
| **Kaart** | Is dit 'm? | kijken, bijsturen met één tik, meenemen |

Alles wat er nu nog is (bibliotheek, delen, offline, feedback, account) blijft
bestaan maar verhuist naar een tweede laag onder "Mijn routes" en "Ik".

## 3. De drie schermen

### Start (één scherm, drie tikken)

Geen formulier. Drie grote vragen onder elkaar, elk met chips, elk met een
standaardwaarde zodat "Maak mijn route" na nul tikken al werkt:

1. **Wat ga je doen?** Te voet · Lopen · Fietsen. Pas na een keuze verschijnt
   een tweede rij (Wandelen/Trail, Weg/Trail, Stad/Toer/Koers/Gravel/MTB).
   Nooit acht knoppen in één rij.
2. **Vanwaar?** Grote knop *Hier* (GPS) en een zoekveld. Laatst gebruikte
   startpunten als chips.
3. **Hoe lang?** Slider met drie ankers in tijd én afstand ("half uurtje ·
   3 km", "uurtje · 6 km", "namiddag · 15 km"). Tijd is voor iedereen
   begrijpelijker dan kilometers.

Daaronder één knop: **Maak mijn route**. Daaronder, klein: *of vertel het
gewoon* met een tekstveld. Dat is de enige plek waar chat en formulier
samenkomen: beide leiden naar hetzelfde gesprek.

Mobbin-referenties: Mindvalley-onboarding (één vraag per stap, grote chips,
voortgangsbalk, "Skip") en Komoot "Creating a route" (sport kiezen, kaart,
Save/Navigate).

### Gesprek (het taalmodel vraagt, de kaart kijkt mee)

Na "Maak mijn route" gebeurt wat er nu ook gebeurt: de engine maakt een
verkenningsroute (probe) en meet de omgeving. Nieuw is wat daarna komt:

- Het **taalmodel stelt maximaal drie vragen**, elk als een **vraagkaart**
  onderaan het scherm (patroon van de Claude-iOS-app: "1 van 3", genummerde
  opties, een tekstveld "of typ je antwoord", en altijd *Maakt me niet uit*).
  Boven de kaart staat de verkenningsroute al vaag op de kaart, zodat de
  gebruiker ziet waar de vragen over gaan.
- De vragen komen **niet uit een vaste lijst**. Het model krijgt de meting
  van de probe (hoogtemeters, onverhard %, kasseien m, drukke oversteken,
  fietspad %, bos %, water, verlichting, voorzieningen) plus activiteit en
  wat de gebruiker al zei, en kiest zelf wat relevant is. Voorbeelden:
  - wandelen met "kinderen" in de vraag → oversteken, speeltuin, toilet;
  - lopen om 21 u → verlichting, rondjes of lus;
  - gravel in de Vlaamse Ardennen → kasseien, modder, hoogtemeters;
  - stadsfiets in Gent → fietspaden, autoluw, geen tram­sporen.
  - wat al in de eerste zin staat, wordt niet opnieuw gevraagd.
- Elke vraag heeft een **reden in één zin** ("Er ligt 1,8 km kassei op de
  verkenning"). Dat is het bestaande `reden`-veld, nu altijd zichtbaar.
- Antwoorden zijn knoppen. Vrije tekst kan ook en gaat door het model.
- Ongeduldig? Grote knop **Maak 'm maar** slaat de rest over; onbekende
  voorkeuren blijven `null` (niet `false`).

Mobbin-referenties: Claude iOS "Regenerating a message" (vraagkaart met
"2 of 2"), Klarna AI-assistent (chips onder de vraag, "Skip this question"),
UNIQLO-chat (antwoordknoppen als primaire invoer).

### Kaart (resultaat dat zichzelf uitlegt)

Volledig scherm kaart. Onderaan een sheet (patroon van Komoot/AllTrails):

1. **Drie cijfers**: duur · afstand · hoogte. Niet meer. (Komoot toont er
   vier; drie past op elke telefoon zonder scrollen.)
2. **Waarom deze route**: drie tot vijf regels met vinkje of kruisje, uit het
   scoresysteem van §4. Bijvoorbeeld:
   - ✅ Rustig: 91 % autoluw
   - ✅ Groen: 58 % door bos en park
   - ⚠️ Twee drukke oversteken (bij de Brusselsesteenweg)
   - ❌ Geen café rond km 4 gevonden
   Een kruisje is eerlijk, en is meteen de aanleiding voor bijsturen.
3. **Bijsturen met één tik**: chips die het model afleidt uit de kruisjes en
   het gesprek: *Korter* · *Rustiger* · *Meer bos* · *Andere kant op* ·
   *Zonder die oversteek*. Elke chip is een vooraf berekend `adjust_route`-
   voorstel (zoals `proposals.py` nu al twee voorstellen levert), dus geen
   modelronde nodig bij het tikken.
4. **Neem mee**: één grote knop die een sheet opent met *Op mijn telefoon
   (offline)*, *Naar mijn Garmin/Wahoo (FIT)*, *GPX*, *Deel link*. De namen
   zeggen wat je ermee doet, niet welk bestandsformaat het is.
5. Een tekstveld *Zeg wat je anders wil* blijft onderaan.

Een route die nog op antwoorden wacht is **nooit** een lege kaart: de sheet
toont dan de openstaande vraagkaart met de verkenningsroute erachter.

Mobbin-referenties: Komoot route-sheet (Duration/Distance/Uphill, Save +
Navigate), AllTrails (Download + Start), Transit ("94 % on safe routes" als
één begrijpelijke kwaliteitsregel), Strava-kaart ("100 % Paved"-badge).

## 4. Het scoresysteem op maat

Vandaag: vijf vaste gewichten in het profiel, de optimizer maximaliseert één
`doel`, en de rest zijn ja/nee-schakelaars in het custom model van GraphHopper.

Voorstel: het gesprek levert een **criterialijst** die per route en per
gebruiker anders is. Een criterium is een klein, deterministisch object:

```json
{
  "id": "rustig",
  "label": "Rustig, weinig auto's",
  "metriek": "autovrij_pct",
  "richting": "hoog",
  "gewicht": 0.4,
  "hard": false,
  "bron": "gebruiker zei 'met de kinderen'"
}
```

- **Metriek** is altijd iets dat de engine kan meten op een geometrie. De
  bestaande metrieken (`hoogtemeters`, `offroad_pct`, `kassei_m`,
  `steenweg_m`, `oversteken`, `fietspad_pct`, `populair_pct`, `water_pct`,
  `closure_m`, `overlap_m`) worden aangevuld met wat het gesprek vaak nodig
  heeft: `bos_pct` en `groen_pct` (landuse), `verlicht_pct` (`lit=yes`),
  `schaduw_pct` (bos + bomenrij), `trappen` (`highway=steps`), `poi_binnen_m`
  per soort (speeltuin, toilet, café, water, bank), `rondjes` (hoe vaak
  dezelfde lus). Alles komt uit OSM dat al in de pack zit.
- **Hard** criteria worden filters of custom-modelregels (zoals `strict` en
  `vermijd_plaatsen` nu). Zachte criteria tellen in de score.
- **Score** = gewogen som van genormaliseerde metrieken over de kandidaten
  die de optimizer nu al maakt (tot 8 exact gerouteerde kandidaten per
  ronde, `round_trip`-varianten). De optimizer kiest dus niet meer "meeste
  hoogtemeters" maar "hoogste score voor deze criterialijst". Het huidige
  `doel` wordt één criterium met gewicht 1,0; bestaande CLI/MCP-contracten
  blijven daardoor werken.
- **Het taalmodel bouwt de lijst, de engine rekent.** Het model krijgt een
  tool `stel_criteria(lijst)` met een gesloten set metriek-id's. Het mag
  labels en gewichten verzinnen, geen metrieken. Dat houdt de evalpoort
  (`model_gate`) en de deterministische `answers`-weg intact: een knopantwoord
  zet rechtstreeks een criterium, zonder modelronde.
- **Uitleg is gratis.** De "Waarom deze route"-regels van §3 zijn precies de
  criteria met hun gemeten waarde en een drempel. Geen apart uitlegmodel.
- **Onthouden.** De criterialijst wordt bij de route bewaard (zoals
  `constraints` nu in `route-summary-v2`) en de terugkerende criteria van een
  gebruiker worden zijn profiel. "Zoals vorige keer" wordt dan één chip op
  het startscherm.

Wat dit níét is: een sliderpaneel met twaalf gewichten. De gebruiker ziet
nooit getallen van 0 tot 1, alleen zinnen met vinkjes.

## 5. Rolverdeling model en engine

| Stap | Wie | Waarom |
|---|---|---|
| Vraag begrijpen, activiteit en startpunt kiezen | model (met `lookup_place`) | taal |
| Verkenningsroute en meting | engine | deterministisch, al gebouwd |
| Vragen kiezen en formuleren | model, op basis van de meting | situationeel, geen vaste lijst |
| Antwoord van een knop verwerken | engine (`answers`-endpoint) | geen modelronde, geen 1-van-2-fout van gpt-oss |
| Criterialijst opstellen | model via `stel_criteria` | op maat |
| Kandidaten maken en scoren | engine | rekenwerk, binnen Lambda |
| "Waarom"-regels en bijstuurchips | engine | afgeleid van criteria en metingen |
| Vrije bijstuurtekst | model → `adjust_route` | taal |

Het model is dus de gesprekspartner en de vertaler; het rekent nooit zelf.
Dat is ook de reden dat het pilotmodel (gpt-oss) voldoende kan zijn: de
foutgevoelige stappen lopen om het model heen.

## 6. Wat verdwijnt

- Het Routeatelier met klimknoppen, doelknoppen en vermijdveld als zichtbaar
  paneel. Klimmen worden gewone voorstellen ("Molenberg erbij, +2 km") en
  gewone criteria ("veel hoogtemeters").
- Het aparte snelformulier naast de chat. Er is één start.
- Sidebar-eerst. Bibliotheek en gesprekken zitten onder "Mijn routes".
- Vaste profielgewichten als instelling. Profiel = onthouden criteria.
- De acht activiteitsknoppen op één rij.

CLI en MCP blijven ongewijzigd werken; alleen de webapp en de chat-tools
veranderen. `plan_route`/`adjust_route` krijgen een optioneel `criteria`-veld.

## 7. Uitvoering in slices (elk apart live te zetten)

1. **Kaart-sheet met "Waarom deze route"** op de bestaande metrieken, en
   bijstuurchips uit `proposals`. Geen modelwijziging. Grootste zichtbare
   winst, kleinste risico.
2. **Startscherm in drie tikken** (activiteit in twee lagen, Hier/zoeken,
   tijd-slider) dat het bestaande snelplanner-endpoint aanroept. Chat en
   formulier samenvoegen tot één gesprek.
3. **Vraagkaarten** in plaats van losse knoppen in de chat; de bestaande
   vijf vragen eerst, met reden en *Maakt me niet uit*.
4. **Criterialijst in de engine**: metriek-register, score over kandidaten,
   `criteria` in de contracten en in `route-summary`. Cassettes en
   contractmatrix bijwerken. Nieuwe metrieken (bos, verlicht, trappen, POI's)
   uit de pack.
5. **Model kiest de vragen en bouwt criteria** via `stel_criteria`, achter de
   evalpoort. Hosted evals uitbreiden met criteria-cases.
6. **Profiel = onthouden criteria**, chip "Zoals vorige keer".

Slices 1 tot 3 raken alleen de webapp en bestaande endpoints en kunnen voor de
pilot. Slices 4 tot 6 zijn engine- en modelwerk en komen na de eerste
pilotmetingen, zodat de criteria die mensen écht noemen de metrieklijst
bepalen.

## 8. Open vragen voor Mathias

- Tijd of afstand als hoofdmaat op het startscherm? Voorstel: tijd, met
  afstand ernaast.
- Mag het model vragen stellen vóór de verkenning (goedkoper, minder gericht)
  of alleen erna (zoals nu)? Voorstel: alleen erna, behalve wanneer
  activiteit of startpunt ontbreekt.
- Hoeveel vragen maximaal? Voorstel: drie, en nooit twee keer dezelfde.

## Bronnen

- Mobbin: [Mindvalley onboarding](https://mobbin.com/flows/05c98b08-418d-4892-afe4-bdefdafb627e),
  [Claude iOS vraagkaart](https://mobbin.com/flows/c3062c62-4146-457b-8360-67bd657d066b),
  [Klarna AI-chat met chips](https://mobbin.com/flows/42b2cb68-706b-46ea-9612-9acbe53917da),
  [Komoot route maken](https://mobbin.com/flows/73ddca56-204c-406f-ad27-38716956e9fb),
  [Komoot route-sheet](https://mobbin.com/screens/ed774806-05f0-4046-a22f-0fb2d2d1fca6),
  [AllTrails download/start](https://mobbin.com/screens/04ec06c3-44a5-4a0d-b56b-af0026818cae),
  [Transit "94 % on safe routes"](https://mobbin.com/screens/c88b39a9-350c-4467-86ab-1baf574bc4f5).
- Repo: `lusmaker/questions.py`, `profiles.py`, `proposals.py`, `quality.py`,
  `optimizer.py`, `aws_chat.py` (SYSTEM_PROMPT), `web/components/quick-plan.tsx`,
  `route-detail.tsx`, `route-questions.tsx`, issue #29.
