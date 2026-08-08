"""Pure contracttests voor de statische ChatGPT Apps-component."""

from pathlib import Path


COMPONENT = (
    Path(__file__).parents[1] / "lusmaker" / "appsdk" / "preview-component.html"
)


def test_component_uses_openai_globals_without_embedded_route_data():
    document = COMPONENT.read_text(encoding="utf-8")

    assert "window.openai?.toolOutput" in document
    assert "openai:set_globals" in document
    assert "window.openai.requestDisplayMode({mode: 'fullscreen'})" in document
    assert "https://unpkg.com/leaflet@1.9.4" in document
    assert "https://tile.openstreetmap.org" in document
    assert "_geometry" not in document
    assert "const data = {" not in document
