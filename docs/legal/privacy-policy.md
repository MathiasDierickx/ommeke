# Privacybeleid Lusmaker

> **CONCEPT — vereist juridische review en invulling van de bedrijfsgegevens
> vóór publicatie.** De Claude-connectordirectory weigert submissions zonder
> publiek bereikbaar privacybeleid; publiceer dit (na review) op
> `https://<domein>/privacy`.

*Technische inventaris: 2 oktober 2026; juridische review nog vereist.*

## Wie we zijn

Lusmaker ("wij") is een dienst van [BEDRIJFSNAAM / Mathias Dierickx],
[adres], België — contact: [e-mail]. Lusmaker stelt fiets- en looproutes
samen op basis van jouw voorkeuren, via AI-assistenten (zoals Claude en
ChatGPT) die met onze dienst verbinden.

## Welke gegevens we verwerken

| categorie | voorbeelden | doel | bewaartermijn |
|---|---|---|---|
| Accountgegevens | e-mailadres, gebruikers-ID van je AI-assistent-login (OAuth) | authenticatie, jouw routes aan jou koppelen | tot verwijdering van je account |
| Voorkeurenprofiel | gewichten (klimmen/offroad), voorkeuren (kasseien, autovrij), antwoordhistoriek | betere routes voorstellen | tot je ze wist of je account verwijdert |
| Routes en concepten | startpunten (adres!), routes, GPX-exports | de kerndienst | tot je ze wist; exports max. [30] dagen |
| Technische logs | IP-adres, tijdstippen, foutmeldingen | beveiliging, misbruikpreventie | max. [90] dagen |

Startpunten kunnen je woonadres onthullen; we behandelen route- en
profielgegevens daarom als persoonsgegevens onder de AVG/GDPR.

## Eigen webapp en modelverwerking

De eigen chat bewaart berichten, assistentantwoorden en gekoppelde routes in
DynamoDB en verstuurt context naar AWS Bedrock. De MCP-connector ontvangt
 tool-aanroepen; deze beperking geldt niet voor onze eigen chat. Tenantopslag
bevat ook feedback, quota en requestreceipts. Vercel host de frontend en AWS
Cognito verzorgt authenticatie. Optionele Google-geocoding verstuurt zoektermen;
externe kaarttiles kunnen IP-adres en gevraagde kaartregio aan de provider tonen.
Concrete regio's, verwerkers en doorgiftegrondslagen moeten worden bevestigd.

Delen is opt-in: iedereen met de link ziet routegeometrie inclusief startpunt.
De link kan worden ingetrokken. Account-export downloadt actieve gegevens.
Wissing blokkeert nieuw werk en vraagt na 16 minuten opnieuw bevestiging; dan
verdwijnen actieve chats, routes, deelverwijzingen en het Cognito-account.
Een blokkeermarker blijft staan. Historische S3-versies, backups en logs vallen
onder afzonderlijke, vóór lancering vast te leggen retentie. Zie OPERATIONS.md.

## Wat we NIET doen

- Geen verkoop of verhuur van je gegevens.
- Geen advertentieprofilering.
- Geen training van AI-modellen op jouw routes of profielen.
- De nieuwe applicatiemetrieken bevatten geen prompts of routegeometrie.

## Rechtsgrond

Uitvoering van de overeenkomst (art. 6.1.b AVG) voor de kerndienst;
gerechtvaardigd belang (art. 6.1.f) voor beveiligingslogs.

## Verwerkers en doorgifte

Hosting bij Amazon Web Services ([regio, bv. eu-west-1 — EU]); routing- en
kaartdata op onze eigen infrastructuur. Volledige verwerkerslijst op
aanvraag. De concrete modelregio en eventuele doorgiften moeten vóór publicatie worden bevestigd.

## Open data

Route-berekening gebruikt open databronnen (OpenStreetMap, Toerisme
Vlaanderen open data, open hoogtedata). De server gebruikt vooraf ingelezen data; interactieve kaarttiles en optionele geocoding zijn hierboven afzonderlijk beschreven.

## Jouw rechten

Inzage, rectificatie, wissing, beperking, overdraagbaarheid en bezwaar:
mail [e-mail]. Je kunt je profiel en routes ook rechtstreeks via de
assistent wissen. Klachten: Gegevensbeschermingsautoriteit (België),
www.gegevensbeschermingsautoriteit.be.

## Beveiliging

Versleuteld transport (TLS), OAuth 2.1-authenticatie, gegevens per gebruiker
gescheiden opgeslagen, toegang beperkt tot [wie].

## Wijzigingen

Wezenlijke wijzigingen kondigen we aan op deze pagina met nieuwe datum.
