# T1 — `lus draft optimize`: de greedy-lus in de tool

## Waarom

In de PoC stuurde de LLM de lus suggest→add-climb→route handmatig aan. Dat is
traag (veel tool-calls), niet-deterministisch en gevoelig voor schattingsdrift
(voorspelde extra ~1-2 km lager dan werkelijk). Deze taak verplaatst die lus
naar de tool. Zie PRODUCT.md M1.

## Commando

```
lus draft optimize <id> --max-km 45 [--objective hm|hm-per-km]
                        [--min-ratio 8] [--max-rounds 12]
```

- `--max-km` (verplicht): hard afstandsbudget voor het eindtotaal.
- `--objective` (default `hm`): `hm` = kies per ronde de kandidaat met de
  meeste extra hoogtemeters; `hm-per-km` = beste verhouding
  extra_hoogtemeters / extra_km.
- `--min-ratio` (default 8): kandidaten onder deze hm/km-verhouding negeren.
- `--max-rounds` (default 12): bovengrens op greedy-rondes.

## Algoritme (deterministisch)

1. Laad draft + klimpool (`climbs.all_climbs()`). Als de draft geen enkele
   klim heeft en `loop` is: kies een **anker** — de klim met de hoogste
   `gain_m` waarvan de geschatte rondrit past:
   `2 * haversine(start, klim.foot) * 1.3 + klim.length_m <= max_km * 1000`.
   Geen kandidaat → `{"error": "geen klim bereikbaar binnen het budget"}`.
2. Routeer (`draft.route`) als `computed` ontbreekt. Als het totaal nu al
   boven `max_km` zit → error met duidelijke boodschap.
3. Greedy-rondes, max `--max-rounds`:
   a. `budget = max_km - computed.total_km`; stop als `budget < 1.0`.
   b. Kandidaten via de bestaande suggest-kern met
      `max_detour_km = budget * 0.85` (veiligheidsmarge voor drift) en
      `limit = 10`; verban kandidaten uit een eerdere rollback (zie 3e).
   c. Filter op `extra_hoogtemeters / max(extra_km, 0.3) >= min_ratio` en
      `extra_km <= budget * 0.85`. Geen kandidaten → klaar.
   d. Kies volgens `--objective`; voeg toe op `invoegen_op_positie`;
      herrouteer.
   e. **Budget-guard**: nieuw totaal > `max_km` → klim verwijderen,
      herrouteren, kandidaat op de banlijst, ronde telt wel mee.
4. Output-JSON:

```json
{
  "id": "...",
  "objective": "hm",
  "max_km": 45.0,
  "resultaat": { ...draft.summary(d)... },
  "rondes": [
    {"ronde": 1, "toegevoegd": "auto-kampenheuvel", "voorspeld_extra_km": 2.8,
     "totaal_na": 36.0, "status": "geaccepteerd"},
    {"ronde": 2, "toegevoegd": "auto-x", "totaal_na": 46.1,
     "status": "teruggedraaid (budget)"}
  ],
  "gestopt_omdat": "geen kandidaten boven min-ratio binnen budget"
}
```

## Implementatie-aanwijzingen

- Refactor `draft.suggest` minimaal: splits een kern
  `_candidates(d, climb_db, max_detour_km, limit, banned=frozenset())` af die
  de lijst dicts teruggeeft; `suggest` en `optimize` gebruiken beide die kern.
  `banned` filtert op klim-id vóór de dure exact-berekening.
- `draft.optimize(d, climb_db, max_km, objective="hm", min_ratio=8.0,
  max_rounds=12) -> dict` in `draft.py`; CLI-wiring in `cli.py`.
- Router-calls blijven via de bestaande paden (`gh.route` in suggest/route);
  maak in `optimize` zelf géén directe gh-calls behalve via route/suggest-kern.
- Denk aan draft-persistentie: na elke accept/rollback `draft.save`.
- Documenteer het commando in `CLAUDE.md` (flow-sectie) en `README.md`
  (gebruik + roadmap-vinkje M1).

## Tests (puur, geen netwerk)

Maak `tests/run.py` (runner, zie AGENTS.md) en `tests/test_optimize.py`:

- ankerkeuze: synthetische klimpool + startpunt → juiste klim gekozen, en
  error-dict wanneer niets past. (Maak de ankerkeuze een pure functie, bv.
  `_pick_anchor(start, climbs, max_km)`.)
- kandidaatfilter: ratio- en budgetfilter + banlijst als pure functie testen.
- budget-guard-besluit: pure functie `_over_budget(total_km, max_km)` hoeft
  niet — test de filterlogica en de objective-keuze (`hm` vs `hm-per-km`)
  op een lijstje synthetische kandidaten.

## Definition of done

- `.venv/bin/lus draft optimize --help` toont het commando.
- `.venv/bin/python -m tests.run` groen.
- Geen wijzigingen aan bestaande outputvelden.
- Commit(s) met heldere message; niet pushen.
