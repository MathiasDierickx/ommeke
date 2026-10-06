# Privacybeleid Lusmaker

> **CONCEPT — vereist juridische review en invulling van de bedrijfsgegevens
> vóór publicatie.** De Claude-connectordirectory weigert submissions zonder
> publiek bereikbaar privacybeleid; publiceer dit (na review) op
> `https://<domein>/privacy`.

*Technische inventaris: 2 oktober 2026; juridische review nog vereist.*

## Wie we zijn

Lusmaker ("wij") is een dienst van Ommeke (in pilotfase), beheerd door
Mathias Dierickx, België. Postadres: [POSTADRES — nog in te vullen door de
eigenaar]. Contact: mathias.dierickx@gmail.com (publiek contactadres, bevestigd
door de eigenaar op 6 oktober 2026). Lusmaker stelt fiets- en looproutes
samen op basis van jouw voorkeuren, via AI-assistenten (zoals Claude en
ChatGPT) die met onze dienst verbinden.

## Welke gegevens we verwerken

| categorie | voorbeelden | doel | bewaartermijn |
|---|---|---|---|
| Accountgegevens | e-mailadres, gebruikers-ID van je AI-assistent-login (OAuth) | authenticatie, jouw routes aan jou koppelen | tot verwijdering van je account |
| Voorkeurenprofiel | gewichten (klimmen/offroad), voorkeuren (kasseien, autovrij), antwoordhistoriek | betere routes voorstellen | tot je ze wist of je account verwijdert |
| Routes en concepten | startpunten (adres!), routes, GPX-exports | de kerndienst | tot je ze wist of je account verwijdert; GPX-exports horen bij de route en worden samen met die route gewist |
| Technische logs | IP-adres, tijdstippen, foutmeldingen | beveiliging, misbruikpreventie | 7 dagen in CloudWatch (instelling `log_retention_days`) |

Startpunten kunnen je woonadres onthullen; we behandelen route- en
profielgegevens daarom als persoonsgegevens onder de AVG/GDPR.

## Eigen webapp en modelverwerking

De eigen chat bewaart berichten, assistentantwoorden en gekoppelde routes in
DynamoDB en verstuurt context (maximaal twintig recente berichten) naar AWS
Bedrock in eu-west-1; het productiemodel is momenteel `openai.gpt-oss-120b-1:0`.
De Claude-connector (MCP) ontvangt alleen tool-aanroepen, geen gesprekstekst;
deze beperking geldt niet voor onze eigen chat. Tenantopslag
bevat ook feedback, quota en requestreceipts. Vercel host de frontend en AWS
Cognito verzorgt authenticatie. Optionele Google-geocoding verstuurt zoektermen;
externe kaarttiles kunnen IP-adres en gevraagde kaartregio aan de provider tonen.
AWS Bedrock gebruikt invoer en uitvoer niet om modellen te trainen. De
eventuele doorgiftegrondslagen voor Vercel en Google moeten nog worden bevestigd.

Delen is opt-in: iedereen met de link ziet routegeometrie inclusief startpunt.
De link kan worden ingetrokken. Account-export downloadt actieve gegevens.
Wissing blokkeert nieuw werk en vraagt na 16 minuten opnieuw bevestiging; dan
verdwijnen actieve chats, routes, deelverwijzingen en het Cognito-account.
Een blokkeermarker blijft staan. Historische S3-versies van verwijderde
objecten verdwijnen na 30 dagen, technische logs na 7 dagen. DynamoDB
point-in-time recovery staat standaard uit, dus er zijn geen extra
DynamoDB-back-ups. Zie `docs/OPERATIONS.md`.

## Wat we NIET doen

- Geen verkoop of verhuur van je gegevens.
- Geen advertentieprofilering.
- Geen training van AI-modellen op jouw routes of profielen.
- De nieuwe applicatiemetrieken bevatten geen prompts of routegeometrie.

## Rechtsgrond

Uitvoering van de overeenkomst (art. 6.1.b AVG) voor de kerndienst;
gerechtvaardigd belang (art. 6.1.f) voor beveiligingslogs.

## Verwerkers en doorgifte

Hosting bij Amazon Web Services (regio eu-west-1, Ierland — EU); routing- en
kaartdata op onze eigen infrastructuur. Volledige verwerkerslijst op
aanvraag. Bedrock-inferentie draait in dezelfde regio; bevestig vóór publicatie of het gekozen model geen regio-overschrijdende inferentie gebruikt.

## Open data

Route-berekening gebruikt open databronnen (OpenStreetMap, Toerisme
Vlaanderen open data, open hoogtedata). De server gebruikt vooraf ingelezen data; interactieve kaarttiles en optionele geocoding zijn hierboven afzonderlijk beschreven.

## Jouw rechten

Inzage, rectificatie, wissing, beperking, overdraagbaarheid en bezwaar:
mail mathias.dierickx@gmail.com. Je kunt je profiel en routes ook rechtstreeks via de
assistent wissen. Klachten: Gegevensbeschermingsautoriteit (België),
www.gegevensbeschermingsautoriteit.be.

## Beveiliging

Versleuteld transport (TLS), OAuth 2.1-authenticatie, gegevens per gebruiker
gescheiden opgeslagen, toegang tot de productieomgeving beperkt tot de beheerder (Mathias Dierickx).

## Wijzigingen

Wezenlijke wijzigingen kondigen we aan op deze pagina met nieuwe datum.

## Nog te beslissen door de eigenaar

- Postadres invullen.
- Juridische review en publicatie op `https://<domein>/privacy`.
