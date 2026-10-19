import importlib.util
import tempfile
from pathlib import Path

from lusmaker import gpx
from lusmaker.fit_course import encode

_spec = importlib.util.spec_from_file_location("inspect_download", Path(__file__).resolve().parent.parent / "scripts" / "inspect_download.py")
inspect_download = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inspect_download)

DRAFT = {"name": "Proeflus", "profile": "trail", "climbs": [], "start": [51.0, 3.0], "computed": {"total_km": 1.7},
         "_geometry": [[[51.0, 3.0, 5], [51.0, 3.01, 12], [51.001, 3.005, 8], [51.0, 3.0, 5]]],
         "cues": [{"lat": 51.0, "lon": 3.005, "text": "Rechtsaf", "sign": 2}]}


def test_inspect_gpx_en_fit_geven_zelfde_lus():
  with tempfile.TemporaryDirectory() as temp_dir:
    tmp_path = Path(temp_dir)
    gpx_path = tmp_path / "lus.gpx"
    gpx.export(DRAFT, {}, str(gpx_path), pois=[])
    fit_path = tmp_path / "lus.fit"
    fit_path.write_bytes(encode(DRAFT, {}, timestamp=1760000000, pois=[]))

    g = inspect_download.inspect(gpx_path)
    f = inspect_download.inspect(fit_path)
    assert g["formaat"] == "gpx" and f["formaat"] == "fit"
    assert g["trackpunten"] == f["trackpunten"] == 4
    assert abs(g["lengte_m"] - f["lengte_m"]) < 2
    assert g["sluiting_m"] == 0.0 and f["sluiting_m"] < 1
    assert g["aanwijzingen"] == f["aanwijzingen"] == 1
    assert f["sport"] == "walking" and f["crc_ok"]


def test_inspect_onleesbaar_bestand():
  with tempfile.TemporaryDirectory() as temp_dir:
    bad = Path(temp_dir) / "x.gpx"
    bad.write_bytes(b"<gpx/>")
    assert inspect_download.main([str(bad)]) == 1
