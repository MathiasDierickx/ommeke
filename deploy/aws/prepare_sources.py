"""Activeer een gecontroleerd open-datapack in de Lambda-buildcontext."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lusmaker import route_sources


def prepare(build: Path, destination: Path) -> dict:
    report = route_sources.verify(build)
    manifest = json.loads((build / "manifest.json").read_text())
    if manifest.get("contains_personal_heat") is not False:
        raise ValueError("alleen expliciet publieke routedatapacks mogen naar AWS")
    if (not (destination / "regions.json").is_file()
            or not (destination / "regions/vlaanderen/gh/config.yml").is_file()):
        raise ValueError("bereid eerst het Vlaamse GraphHopper-regiopack voor")
    with route_sources._home(destination.resolve()):
        installed = route_sources.install(build, apply=True)
        # mkdtemp/NamedTemporaryFile geven lokaal bewust 700/600. Docker COPY
        # bewaart die rechten, terwijl Lambda als een andere gebruiker draait.
        # Alleen dit gecontroleerde publieke pack krijgt gedeelde leesrechten.
        public_pack = Path(installed["bestemming"])
        public_pack.parent.chmod(0o755)
        public_pack.chmod(0o755)
        for path in public_pack.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        (public_pack.parent / "current.json").chmod(0o644)
        from lusmaker import route_evidence
        database = route_evidence.database_path()
        if database is None:
            raise ValueError("de cloudengine kan de geïnstalleerde segmentdatabase niet vinden")
    return {**report, "database": str(database), "toegepast": installed["toegepast"],
            "graphhopper_herimporteerd": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.build, args.destination)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
