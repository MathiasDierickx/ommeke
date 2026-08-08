"""lus — CLI om stap voor stap fiets- en trail-GPX-lussen te bouwen.

Alle output is JSON zodat een LLM (Claude/OpenAI) de tool kan aansturen.
"""
import argparse
import json
import sys

from . import config


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _err(msg: str) -> None:
    print(json.dumps({"error": str(msg)}, ensure_ascii=False, indent=2))
    sys.exit(1)


def _parse_point(s: str, limit: int = 1):
    """'lat,lon' of een plaats-/straatnaam via de lokale geocoder."""
    from . import geocode

    return geocode.resolve(s)


def parse_weights(value: str) -> dict:
    """Parseer ``naam=getal``-paren en vul ontbrekende objectives met nul."""
    from . import profiles

    parsed = {}
    for part in value.split(","):
        if "=" not in part:
            raise ValueError("gewichten zijn komma-gescheiden naam=getal-paren")
        name, raw = (piece.strip() for piece in part.split("=", 1))
        if not name or name in parsed:
            raise ValueError("elk gewicht moet precies één geldige naam hebben")
        try:
            parsed[name] = float(raw)
        except ValueError as exc:
            raise ValueError(f"gewicht '{name}' moet een getal zijn") from exc
    # Validatie + normalisatie gebeurt in de optimizer/profielmodule; de CLI
    # bewaart de door de gebruiker opgegeven verhouding.
    unknown = set(parsed) - set(profiles.WEIGHT_KEYS)
    if unknown:
        raise ValueError(f"onbekend gewicht: {sorted(unknown)[0]}")
    if not parsed:
        raise ValueError("geef minstens één gewicht op")
    return {key: parsed.get(key, 0.0) for key in profiles.WEIGHT_KEYS}


# ---------- commands ----------

def cmd_setup(args):
    from . import data, gh_config

    res = data.setup()
    res["gh_files"] = gh_config.write_gh_files()
    res["volgende_stap"] = "docker compose up -d  (in de lusmaker-repo), daarna `lus build`"
    return res


def cmd_build(args):
    from . import climbs, osm

    extract = osm.build_extract(force=args.force)
    osm.build_gazetteer(extract, force=args.force)
    if config.current_region().slug == config.LEGACY_SLUG:
        res = climbs.resolve_all(extract, force=True)
    else:
        config.ensure_dirs()
        config.CLIMBS_JSON.write_text(
            json.dumps({"climbs": {}, "failed": []}), encoding="utf-8"
        )
        res = {"climbs": {}, "failed": []}
        climbs.detect_auto(extract)
    return {
        "ok": True,
        "wegen_in_regio": len(extract["ways"]),
        "plaatsen": len(extract["places"]),
        "klimmen_opgelost": len(res["climbs"]),
        "klimmen_niet_opgelost": res["failed"],
    }


def cmd_status(args):
    return config.status(args.region)


def cmd_profile_show(args):
    from . import profiles

    return profiles.load(args.naam)


def cmd_profile_list(args):
    from . import profiles

    return {"profielen": profiles.list_all()}


def cmd_profile_set(args):
    from . import profiles

    patch = {}
    if args.activiteit is not None:
        patch["activiteit"] = args.activiteit
    if args.gewichten is not None:
        patch["gewichten"] = parse_weights(args.gewichten)
    preferences = {
        key: value
        for key, value in {
            "kasseien": args.kasseien,
            "beton": args.beton,
            "steenwegen": args.steenwegen,
            "autovrij": args.autovrij,
        }.items()
        if value is not None
    }
    if args.vermijd_plaats is not None:
        preferences["vermijd_plaatsen"] = args.vermijd_plaats
    if preferences:
        patch["voorkeuren"] = preferences
    if not patch:
        raise ValueError("geef minstens één profielwijziging op")
    return profiles.apply_patch(args.naam, patch, bron="cli")


def cmd_region_add(args):
    from . import regions

    return regions.install(
        args.slug, args.geofabrik, regions.parse_bbox(args.bbox)
    )


def cmd_region_list(args):
    from . import regions

    return regions.list_all()


def cmd_region_default(args):
    from . import regions

    return regions.set_default(args.slug)


def cmd_region_migrate_legacy(args):
    from . import regions

    return regions.migrate_legacy()


def cmd_region_ensure(args):
    from . import provision

    return provision.ensure_region(args.place)


def cmd_region_status(args):
    from . import provision

    return provision.region_status(args.slug)


def cmd_region_pack(args):
    from . import provision

    return provision.create_pack(args.slug, args.output)


def cmd_geocode(args):
    from . import geocode

    return {"query": args.query, "resultaten": geocode.geocode(args.query, limit=args.limit)}


def cmd_climbs_list(args):
    from . import climbs

    db = climbs.load()
    return {
        "klimmen": [climbs.summary(c) for c in sorted(db["climbs"].values(), key=lambda c: c["id"])],
        "niet_opgelost": db["failed"],
    }


def cmd_climbs_near(args):
    from . import climbs, geo

    point, _ = _parse_point(args.plaats)
    db = {"climbs": climbs.all_climbs()}
    out = []
    for c in db["climbs"].values():
        dist = geo.haversine(point["lat"], point["lon"], c["foot"][0], c["foot"][1])
        if dist <= args.radius_km * 1000:
            s = climbs.summary(c)
            s["afstand_km"] = round(dist / 1000, 1)
            out.append(s)
    out.sort(key=lambda c: c["afstand_km"])
    return {"bij": point["label"], "klimmen": out}


def cmd_climbs_resolve(args):
    from . import climbs, osm

    extract = osm.build_extract()
    if config.current_region().slug == config.LEGACY_SLUG:
        res = climbs.resolve_all(extract, force=True)
    else:
        config.ensure_dirs()
        config.CLIMBS_JSON.write_text(
            json.dumps({"climbs": {}, "failed": []}), encoding="utf-8"
        )
        res = climbs.detect_auto(extract)
    return {"opgelost": len(res["climbs"]), "niet_opgelost": res["failed"]}


def cmd_draft_new(args):
    from . import draft

    return draft.create(
        start=args.start, name=args.name, loop=not args.no_loop, end=args.end,
        strict=args.strict, avoid_cobbles=args.vermijd_kasseien,
        avoid_concrete=args.vermijd_beton, avoid_busy=args.autovrij,
        region=args.region,
        profile=args.profiel,
        profile_doc=args.profiel_naam,
    )


def cmd_draft_list(args):
    from . import draft

    return {"drafts": draft.list_all()}


def cmd_draft_show(args):
    from . import draft

    d = draft.load(args.id)
    out = draft.summary(d)
    if args.full:
        out["geometry_legs"] = d.get("_geometry")
    return out


def cmd_draft_delete(args):
    from . import draft

    p = config.drafts_path() / f"{draft.validate_draft_id(args.id)}.json"
    if not p.exists():
        raise RuntimeError(f"draft '{args.id}' bestaat niet")
    p.unlink()
    return {"verwijderd": args.id}


def cmd_draft_add_climb(args):
    from . import draft

    return draft.add_climb(args.id, args.climb, position=args.at)


def cmd_draft_remove_climb(args):
    from . import draft

    return draft.remove_climb(args.id, args.climb)


def cmd_draft_avoid(args):
    from . import draft

    return draft.avoid_place(
        args.id, args.plaats, radius_km=args.radius_km, factor=args.factor
    )


def cmd_draft_unavoid(args):
    from . import draft

    return draft.unavoid_place(args.id, args.plaats)


def cmd_climbs_detect(args):
    from . import climbs, osm

    extract = osm.build_extract()
    res = climbs.detect_auto(extract, min_gain=args.min_gain, min_avg=args.min_avg)
    top = sorted(res["auto"].values(), key=lambda c: -c["gain_m"])[:15]
    return {
        "auto_klimmen": len(res["auto"]),
        "top15_op_hoogtemeters": [climbs.summary(c) for c in top],
    }


def cmd_heat_build(args):
    from . import heat

    return heat.build(min_passes=args.min_passes, osm_min_points=args.osm_min_points)


def cmd_heat_fetch_osm(args):
    from . import heat

    return heat.fetch_osm(max_pages_per_tile=args.max_pages)


def cmd_heat_fetch_vlaanderen(args):
    from . import heat

    return heat.fetch_vlaanderen()


def cmd_heat_status(args):
    from . import heat

    return heat.status()


def cmd_draft_route(args):
    from . import climbs, draft

    d = draft.load(args.id)
    with draft.region_scope(d):
        return draft.route(d, climbs.all_climbs())


def cmd_draft_readiness(args):
    from . import climbs, draft, profiles, readiness

    d = draft.load(args.id)
    with draft.region_scope(d):
        climb_db = climbs.all_climbs()
        draft.probe(d, climb_db)
        return readiness.assess(d, profiles.load(args.profiel_naam), climb_db)


def cmd_draft_suggest(args):
    from . import climbs, draft

    d = draft.load(args.id)
    with draft.region_scope(d):
        sugg = draft.suggest(
            d, climbs.all_climbs(),
            max_detour_km=args.max_detour_km, limit=args.limit,
        )
    return {
        "draft": d["id"],
        "huidige_km": d["computed"]["total_km"],
        "suggesties": sugg,
        "hint": "stel deze aan de gebruiker voor; toevoegen kan met het 'voorstel'-commando",
    }


def cmd_draft_optimize(args):
    from . import climbs, draft

    d = draft.load(args.id)
    with draft.region_scope(d):
        return draft.optimize(
            d, climbs.all_climbs(), max_km=args.max_km,
            objective=(parse_weights(args.gewichten) if args.gewichten else args.objective),
            min_ratio=args.min_ratio,
            max_rounds=args.max_rounds, fill=not args.geen_opvulling,
        )


def cmd_draft_export(args):
    from . import climbs, draft, gpx

    d = draft.load(args.id)
    path = args.output or f"{d['name']}.gpx"
    with draft.region_scope(d):
        return gpx.export(d, climbs.all_climbs(), path)


def cmd_draft_preview(args):
    from . import climbs, draft, preview

    d = draft.load(args.id)
    path = args.output or f"{d['name']}-preview.html"
    with draft.region_scope(d):
        return preview.export(d, climbs.all_climbs(), path)


def cmd_plan_route(args):
    from . import intents

    return intents.plan_route(
        start=args.start,
        region=args.region,
        max_km=args.max_km,
        target_km=args.target_km,
        tolerance_km=args.tolerance_km,
        doel=args.doel,
        via_klimmen=args.via_klim,
        vermijd_plaatsen=args.vermijd_plaats,
        kasseien=args.kasseien,
        beton_vermijden=not args.beton_toestaan,
        autovrij=args.autovrij,
        strict=args.strict,
        naam=args.naam,
        activiteit=args.activiteit,
        geen_opvulling=args.geen_opvulling,
        profiel_naam=args.profiel_naam,
        request_id=args.request_id,
    )


def cmd_adjust_route(args):
    from . import intents

    return intents.adjust_route(
        draft_id=args.id,
        voeg_klimmen_toe=args.voeg_klim_toe,
        verwijder_klimmen=args.verwijder_klim,
        vermijd_plaatsen=args.vermijd_plaats,
        niet_meer_vermijden=args.niet_meer_vermijden,
        sta_plaatsen_toe=args.sta_plaatsen_toe,
        max_km=args.max_km,
        target_km=args.target_km,
        tolerance_km=args.tolerance_km,
        doel=args.doel,
        geen_opvulling=args.geen_opvulling,
        profiel_naam=args.profiel_naam,
        expected_revision=args.expected_revision,
    )


def _region_arg(parser):
    parser.add_argument(
        "--region",
        help="regioslug (overschrijft LUSMAKER_REGION en de default-regio)",
    )


def main(argv=None):
    p = argparse.ArgumentParser(prog="lus", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="download OSM-extract + DEM en schrijf GraphHopper-config")
    _region_arg(s)
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("build", help="bouw lokale caches: extract, gazetteer, klim-database")
    _region_arg(s)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("status", help="check data + GraphHopper")
    _region_arg(s)
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("profile", help="persistente gebruikersvoorkeuren beheren")
    rsub = r.add_subparsers(dest="subcmd", required=True)
    s = rsub.add_parser("show", help="toon een profiel (ontbrekend geeft defaults)")
    s.add_argument("naam", nargs="?", default="standaard")
    s.set_defaults(func=cmd_profile_show)
    s = rsub.add_parser("list", help="toon opgeslagen profielen")
    s.set_defaults(func=cmd_profile_list)
    s = rsub.add_parser("set", help="wijzig voorkeuren en bewaar historiek")
    s.add_argument("naam")
    s.add_argument("--activiteit", choices=("fietsen", "trail"))
    s.add_argument("--gewichten", help="bv. hoogtemeters=0.5,offroad=0.5")
    s.add_argument("--kasseien", choices=("vermijd", "ok", "graag"))
    s.add_argument("--beton", choices=("vermijd", "ok", "graag"))
    s.add_argument("--steenwegen", choices=("vermijd", "ok"))
    s.add_argument("--autovrij", choices=("belangrijk", "ok"))
    s.add_argument("--vermijd-plaats", action="append")
    s.set_defaults(func=cmd_profile_set)

    r = sub.add_parser("region", help="regiopacks beheren")
    rsub = r.add_subparsers(dest="subcmd", required=True)
    s = rsub.add_parser("add", help="download en bouw een nieuw regiopack")
    s.add_argument("slug")
    s.add_argument("--geofabrik", required=True, help="pad zoals europe/netherlands/zeeland")
    s.add_argument("--bbox", required=True, help="minlat,minlon,maxlat,maxlon")
    s.set_defaults(func=cmd_region_add)
    s = rsub.add_parser("list", help="toon geregistreerde regio's en status")
    s.set_defaults(func=cmd_region_list)
    s = rsub.add_parser("default", help="stel de default-regio in")
    s.add_argument("slug")
    s.set_defaults(func=cmd_region_default)
    s = rsub.add_parser("migrate-legacy", help="verplaats bestaande data naar regio vlaanderen")
    s.set_defaults(func=cmd_region_migrate_legacy)
    s = rsub.add_parser(
        "ensure", help="zoek een plaats of slug en provision de kleinste regio"
    )
    s.add_argument("place", help="plaatsnaam of Geofabrik-regioslug")
    s.set_defaults(func=cmd_region_ensure)
    s = rsub.add_parser("status", help="toon de voortgang van regioprovisioning")
    s.add_argument("slug")
    s.set_defaults(func=cmd_region_status)
    s = rsub.add_parser("pack", help="maak een cachebaar regiopack")
    s.add_argument("slug")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_region_pack)

    s = sub.add_parser("geocode", help="zoek een plaats of 'straat, plaats'")
    _region_arg(s)
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_geocode)

    s = sub.add_parser(
        "plan-route",
        help="maak, routeer, preview en exporteer een lus in één stap",
    )
    _region_arg(s)
    s.add_argument("--start", required=True)
    s.add_argument("--profiel-naam", help="persistent voorkeurenprofiel")
    s.add_argument(
        "--activiteit",
        choices=("fietsen", "trail"),
        default="fietsen",
    )
    s.add_argument("--max-km", type=float)
    s.add_argument("--target-km", type=float, help="gewenste routeafstand")
    s.add_argument(
        "--tolerance-km",
        type=float,
        default=2.5,
        help="toegestane afwijking van target-km",
    )
    s.add_argument(
        "--doel",
        choices=("hoogtemeters", "kort", "toeren"),
        default="hoogtemeters",
    )
    s.add_argument("--via-klim", action="append", default=[])
    s.add_argument("--vermijd-plaats", action="append", default=[])
    s.add_argument("--kasseien", action="store_true", help="kasseien zijn toegestaan")
    s.add_argument(
        "--beton-toestaan",
        action="store_true",
        help="vermijd betonbanen niet extra",
    )
    s.add_argument("--strict", action="store_true")
    s.add_argument(
        "--autovrij",
        action="store_true",
        default=None,
        help="prioriteer autovrije en verkeersarme wegen",
    )
    s.add_argument(
        "--geen-opvulling",
        action="store_true",
        help="vul resterend budget niet op met een GraphHopper-rondrit",
    )
    s.add_argument("--naam")
    s.add_argument(
        "--request-id",
        help="stabiele sleutel om een retry van dezelfde route te hervatten",
    )
    s.set_defaults(func=cmd_plan_route)

    s = sub.add_parser(
        "adjust-route",
        help="pas meerdere routewensen toe en routeer eenmaal opnieuw",
    )
    s.add_argument("id")
    s.add_argument("--voeg-klim-toe", action="append", default=[])
    s.add_argument("--verwijder-klim", action="append", default=[])
    s.add_argument("--vermijd-plaats", action="append", default=[])
    s.add_argument("--niet-meer-vermijden", action="append", default=[])
    s.add_argument("--sta-plaats-toe", action="append", default=[])
    s.add_argument("--max-km", type=float)
    s.add_argument("--target-km", type=float)
    s.add_argument("--tolerance-km", type=float)
    s.add_argument("--profiel-naam")
    s.add_argument("--expected-revision", type=int)
    s.add_argument(
        "--doel",
        choices=("hoogtemeters", "kort", "toeren"),
    )
    s.add_argument("--geen-opvulling", action="store_true", default=None)
    s.set_defaults(func=cmd_adjust_route)

    c = sub.add_parser("climbs", help="klim-database")
    csub = c.add_subparsers(dest="subcmd", required=True)
    s = csub.add_parser("list", help="alle opgeloste klimmen")
    _region_arg(s)
    s.set_defaults(func=cmd_climbs_list)
    s = csub.add_parser("near", help="klimmen in de buurt van een punt")
    _region_arg(s)
    s.add_argument("plaats", help="plaatsnaam of lat,lon")
    s.add_argument("--radius-km", type=float, default=15.0)
    s.set_defaults(func=cmd_climbs_near)
    s = csub.add_parser("resolve", help="klim-database opnieuw opbouwen uit climbs.yaml")
    _region_arg(s)
    s.set_defaults(func=cmd_climbs_resolve)
    s = csub.add_parser("detect", help="auto-detectie: DEM-sweep over alle wegen")
    _region_arg(s)
    s.add_argument("--min-gain", type=float, default=18.0)
    s.add_argument("--min-avg", type=float, default=3.0)
    s.set_defaults(func=cmd_climbs_detect)

    h = sub.add_parser("heat", help="persoonlijke en gecureerde populariteitslagen")
    hsub = h.add_subparsers(dest="subcmd", required=True)
    s = hsub.add_parser(
        "build", help="populariteitslagen bouwen uit GPX, OSM en open routedata"
    )
    _region_arg(s)
    s.add_argument("--min-passes", type=int, default=1, help="min. aantal eigen ritten per cel")
    s.add_argument("--osm-min-points", type=int, default=30, help="min. OSM-tracepunten per cel")
    s.set_defaults(func=cmd_heat_build)
    s = hsub.add_parser("fetch-osm", help="publieke OSM GPS-traces downloaden (eenmalig)")
    _region_arg(s)
    s.add_argument("--max-pages", type=int, default=150)
    s.set_defaults(func=cmd_heat_fetch_osm)
    s = hsub.add_parser(
        "fetch-vlaanderen",
        help="Toerisme Vlaanderen fiets- en wandelroutes downloaden",
    )
    _region_arg(s)
    s.set_defaults(func=cmd_heat_fetch_vlaanderen)
    s = hsub.add_parser("status")
    _region_arg(s)
    s.set_defaults(func=cmd_heat_status)

    d = sub.add_parser("draft", help="routes bouwen")
    dsub = d.add_subparsers(dest="subcmd", required=True)
    s = dsub.add_parser("new", help="nieuwe draft")
    _region_arg(s)
    s.add_argument("--start", required=True, help="plaats, 'straat, plaats' of lat,lon")
    s.add_argument("--name")
    s.add_argument("--end", help="eindpunt (anders lus naar start)")
    s.add_argument("--no-loop", action="store_true")
    s.add_argument(
        "--profiel",
        choices=("quiet", "trail"),
        default="quiet",
    )
    s.add_argument("--profiel-naam", help="persistent voorkeurenprofiel")
    s.add_argument("--strict", action="store_true", help="steenwegen maximaal vermijden")
    s.add_argument("--vermijd-kasseien", action="store_true", help="zachte straf op kasseistroken")
    s.add_argument("--vermijd-beton", action="store_true", help="zachte straf op betonbanen")
    s.add_argument(
        "--autovrij",
        action="store_true",
        help="zachte voorkeur voor autovrije en verkeersarme wegen",
    )
    s.set_defaults(func=cmd_draft_new)
    s = dsub.add_parser("list")
    _region_arg(s)
    s.set_defaults(func=cmd_draft_list)
    s = dsub.add_parser("show")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("--full", action="store_true", help="inclusief geometrie")
    s.set_defaults(func=cmd_draft_show)
    s = dsub.add_parser("delete")
    _region_arg(s)
    s.add_argument("id")
    s.set_defaults(func=cmd_draft_delete)
    s = dsub.add_parser("add-climb")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("climb")
    s.add_argument("--at", type=int, help="positie in de klimvolgorde (0-based)")
    s.set_defaults(func=cmd_draft_add_climb)
    s = dsub.add_parser("remove-climb")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("climb")
    s.set_defaults(func=cmd_draft_remove_climb)
    s = dsub.add_parser("avoid", help="zachte vermijdzone rond een plaats")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("plaats")
    s.add_argument("--radius-km", type=float, default=2.5)
    s.add_argument("--factor", type=float, default=0.35)
    s.set_defaults(func=cmd_draft_avoid)
    s = dsub.add_parser("unavoid", help="vermijdzone weghalen")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("plaats")
    s.set_defaults(func=cmd_draft_unavoid)
    s = dsub.add_parser("route", help="routeer alle legs (lus vermijdt eigen heenweg)")
    _region_arg(s)
    s.add_argument("id")
    s.set_defaults(func=cmd_draft_route)
    s = dsub.add_parser(
        "readiness",
        help="verken de route en bepaal welke voorkeuren nog bevraagd moeten worden",
    )
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("--profiel-naam", default="standaard")
    s.set_defaults(func=cmd_draft_readiness)
    s = dsub.add_parser("suggest", help="klimmen die weinig omweg vragen")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("--max-detour-km", type=float, default=10.0)
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_draft_suggest)
    s = dsub.add_parser("optimize", help="vul de route greedy met klimmen binnen een budget")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("--max-km", type=float, required=True, help="hard afstandsbudget")
    objective_group = s.add_mutually_exclusive_group()
    objective_group.add_argument("--objective", choices=("hm", "hm-per-km", "offroad"))
    objective_group.add_argument(
        "--gewichten",
        help="eenmalige mix, bv. hoogtemeters=0.5,offroad=0.5",
    )
    s.add_argument("--min-ratio", type=float, default=8.0, help="minimaal aantal hoogtemeters per extra km")
    s.add_argument("--max-rounds", type=int, default=12, help="maximum aantal greedy-rondes")
    s.add_argument(
        "--geen-opvulling",
        action="store_true",
        help="sla de round_trip-opvulling van resterend budget over",
    )
    s.set_defaults(func=cmd_draft_optimize)
    s = dsub.add_parser("export", help="schrijf GPX")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_draft_export)
    s = dsub.add_parser("preview", help="schrijf een HTML-kaartpreview")
    _region_arg(s)
    s.add_argument("id")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_draft_preview)

    args = p.parse_args(argv)
    try:
        if args.cmd in {"region", "profile"}:
            result = args.func(args)
        else:
            with config.use_region(getattr(args, "region", None)):
                result = args.func(args)
        _out(result)
    except Exception as e:  # nette JSON-fout voor de LLM
        _err(e)


if __name__ == "__main__":
    main()
