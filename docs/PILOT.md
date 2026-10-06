# Pilot met 8 deelnemers

**Periode:** 13 oktober t/m 9 november 2026 (vier weken).  
**Doelgroep:** 8 mensen uit Vlaanderen: 2 wandelaars, 2 lopers/traillopers,
2 stads-/toerfietsers en 2 racefietsers/MTB'ers.

## Hoofdscenario's

1. Maak een route met het snelle formulier en beantwoord situationele vragen.
2. Maak een route in de chat en geef een vervolgwens, bijvoorbeeld
   “café rond km 20”.
3. Pas een route aan, download GPX of FIT en rijd of loop de route echt.

Laat deelnemers waar mogelijk ook op een tweede dag terugkomen. Vraag geen
woonadres; laat hen een publiek startpunt kiezen.

## Meting en succesgrenzen

De bestaande kwaliteitsdrempels blijven gelden; registreer per sessie
pseudoniem, dag, profiel, scenario/vraagcategorie, duur, voltooid, exportformaat,
bruikbaarheid na controle, onbegrepen wens, foutcategorie en vrijwillige
toelichting. De app-feedback kent bruikbaar/verkeerde weg/afstand/wens gemist/
anders.

Meet de trechter met de lokale samenvatter `metrics.summarize` op geëxporteerde
events. Streef naar:

- Geen overschrijding van expliciete afstandsmaxima en geen tenantdatalek.
- Minstens 80% voltooit route → aanpassen → export zonder hulp.
- Minstens 80% beoordeelt de route als bruikbaar na kaart-/ritcontrole.
- P95 end-to-end wachttijd onder vier minuten; rapporteer koud/warm apart.
- `funnel.ready_ratio` (bruikbare `route_ready` / `route_requested`) ≥ 70%.
- `funnel.exported_ratio` (export / bruikbare route) ≥ 50%.
- `funnel.actors.returned_after_export_ratio` ≥ 40% binnen twee weken na
  export. Rapporteer teller en noemer; deelnemers zonder volle observatieperiode
  tellen nog niet mee.
- Mediane wachttijd < 90 seconden; gebruik `latency.*.p50_s` en vermeld welke
  operatie is gemeten.

Dag-twee-terugkeer en kosten per bruikbare route rapporteren met aantallen;
deze kleine steekproef rechtvaardigt geen algemene retentieclaims. Budget:
maximaal 300.000 modeltokens per dag per gebruiker; alarm bij $50 per maand
(issue #5). Houd rekening met de beperking dat `summarize` events nodig heeft
met actor- en datumvelden voor gebruikersmetingen.

## Review en opvolging

Iedere maandag: wekelijkse review van 30 minuten. Bekijk funnel, wachttijden,
feedback en incidenten; zet concrete bevindingen om in GitHub-issues. Noteer
geen niet-gemeten resultaten als feit.

Eigen GPX-import wordt pas een implementatietaak als minstens drie deelnemers
hier concreet behoefte aan hebben. Beslis eerst tussen lokale GPX-upload en
providerintegratie. Vereisten voor upload: tenantisolatie, limieten, duidelijke
wissing/export, geen persoonlijke heat in publieke packs. Geen Strava-sync of
nieuwe afhankelijkheid zonder die keuze.

Platformdistributie: volg submission-checklist.md voor Claude/ChatGPT OAuth,
resourceweergave en goedgekeurde publieke juridische pagina's. Directory-
submissions zijn niet gedaan. Noteer resultaten op issues #7, #17 en #18.
