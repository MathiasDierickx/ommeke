# Ontwerp: eigen ritten importeren

Status: ontwerp voor besluitvorming, nog niet gebouwd. Voorkeursvolgorde: eerst GPX-upload, daarna eventueel Strava- of Garmin-koppeling na apart besluit.

## Doel en gegevensstroom

Geïmporteerde ritten dienen uitsluitend als persoonlijke routevoorkeur. Ze zijn nooit gedeelde populariteitsdata en komen niet in openbare of gedeelde regiopacks.

1. De gebruiker kiest expliciet voor GPX-import en uploadt naar het eigen account. De server valideert bestandstype, omvang, aantal punten en coördinaten. Afgekeurde bestanden worden niet bewaard.
2. Een geïsoleerde verwerker leest trackpunten. Bestandsnaam, tijdstempels en overige GPX-metadata worden standaard niet meegenomen.
3. Trackpunten worden naar rastercellen omgezet met de bestaande geometrische basis uit `lusmaker/heat.py` (`_parse_gpx`, `_track_cells`, `geo.cell`). Per tenant worden activiteitsspecifieke tellingen of gewichten bijgehouden; alleen die tenant kan de heat als persoonlijke voorkeur gebruiken.
4. Ruwe uploads worden na succesvolle verwerking verwijderd. Afgeleide heat blijft in private tenantopslag, gescheiden van open-data-heat, gedeelde packs en beheerder-seeds. Fouten of herverwerking mogen geen data tussen tenants mengen.
5. Bewaar provenance per importbatch zodat een verwijdering de bijdrage uit afgeleide cellen kan halen en de persoonlijke heat opnieuw kan opbouwen.

`heat.py` bouwt nu lokale heatbestanden en weigert hosted heat-writes via `_require_local_admin`. Dit ontwerp vereist daarom tenant-scoped opslag en een expliciete engine-input; lokale `heat build` mag hosted gebruikersdata niet inlezen. De scheiding uit [OPERATIONS.md](../OPERATIONS.md) blijft leidend: gedeelde packs bevatten geen persoonlijke heat.

## Toestemming, ontkoppelen en verwijderen

- Toestemming is expliciet en per bron: GPX-upload, Strava en Garmin vragen elk een eigen opt-in. Providerkoppelingen benoemen welke gegevens en welk tijdvak worden opgehaald.
- Import staat standaard uit. Weigeren beperkt accounttoegang of gewone routeplanning niet.
- Ontkoppelen trekt providerautorisatie in en stopt toekomstige synchronisatie. Reeds geïmporteerde ritten en afgeleide heat blijven staan totdat de gebruiker afzonderlijk kiest voor verwijderen; bied die keuze direct aan.
- Verwijderen wist tijdelijke uploads, importrecords, providerreferenties en alle heatbijdragen van die bron. Accountwissing verwijdert alle persoonlijke heat. Verwijdering moet tenantgebonden zijn en gedeelde heat ongemoeid laten.
- Voorstel bewaartermijn: ruwe GPX alleen tijdens verwerking; persoonlijke afgeleide heat tot intrekking of accountwissing. Bied verwijdering per import en export aan. Dit voorstel en de back-uptermijnen vereisen goedkeuring van eigenaar en juridische review.

## Pilotgegevens voor het bouwbesluit

Sluit aan op het meetprotocol in [PILOT.md](../PILOT.md). Vraag vrijwillig, zonder ritbestanden te verzamelen:

- hoeveel van de 5–10 deelnemers concreet eigen ritten als voorkeur willen gebruiken; de bestaande drempel is minstens drie onafhankelijke gebruikers met concrete behoefte;
- gewenste bron, importfrequentie en historische periode;
- welke routekeuze persoonlijke heat moet verbeteren en waar open/algemene gegevens tekortschieten;
- bereidheid tot toestemming en verwachtingen rond intrekken, verwijderen, export en retentie;
- of een handmatige GPX-upload volstaat of providerkoppeling noodzakelijk is;
- beheerlast tegenover aantoonbaar meer bruikbare routes of herhaald gebruik.

Registreer aantallen en vrijwillige toelichting gepseudonimiseerd volgens het pilotprotocol. Verzin geen resultaten. Bij voldoende behoefte kiest de eigenaar eerst tussen upload en providerintegratie.

## Open vragen voor de eigenaar

- Welke voorkeur beïnvloedt heat: activiteit, ondergrond, populariteit, vermijding of een combinatie?
- Welke GPX-limiet, maximumaantal ritten en importperiode zijn passend?
- Hoe lang bewaren we afgeleide heat en provenance, inclusief S3-versies en backups?
- Welke onderdelen krijgen pilotprioriteit: lokale verwerking, hosted verwerking of beide?
- Is per-brontoestemming genoeg, of is aparte toestemming nodig voor historische import en automatische updates?
- Welke provider wordt eerst onderzocht, en welke scopes, voorwaarden en intrekkingsgedragingen gelden?
- Hoe bevestigen we volledige verwijdering zonder gegevens langer te bewaren dan nodig?
