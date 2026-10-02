"""Provenance en compatibiliteit van lokale regiopacks."""
import hashlib
import json
import pickle
from datetime import datetime, UTC
from . import config
from .osm import EXTRACT_FORMAT_VERSION

PACK_FORMAT_VERSION = 2


def metadata(region):
    extract = {}
    source = region.cache / 'extract.pkl'
    if source.exists():
        try:
            # Alleen onze lokale buildcache; nooit een externe pack hier unpicklen.
            with source.open('rb') as handle:
                extract = pickle.load(handle)
        except (ValueError, EOFError, pickle.UnpicklingError):
            extract = {}
    heat = {}
    if (region.cache / 'heat.pkl').exists():
        with (region.cache / 'heat.pkl').open('rb') as handle:
            heat = pickle.load(handle)
    personal = bool(heat.get('personal_data') or heat.get('files') or heat.get('own_cells') or heat.get('activity_cells'))
    hashes = {}
    for path in sorted((region.gh_dir / 'custom_models').glob('*.json')):
        hashes[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
    area_ids = []
    for path in sorted((region.gh_dir / 'custom_areas').glob('*.geojson')):
        document = json.loads(path.read_text())
        area_ids.extend(feature.get('id') for feature in document.get('features', []) if feature.get('id'))
    return {
        'pack_format_version': PACK_FORMAT_VERSION,
        'built_at': datetime.now(UTC).isoformat(),
        'extract_format_version': extract.get('format_version'),
        'source_cache_modified_at': datetime.fromtimestamp(source.stat().st_mtime, UTC).isoformat() if source.exists() else None,
        'features': {'landmarks': bool(extract.get('landmarks')), 'waterways': bool(extract.get('waterways')), 'areas': sorted(set(area_ids))},
        'model_sha256': hashes,
        'contains_personal_heat': personal,
    }


def validate(manifest):
    version = manifest.get('pack_format_version', 1)
    if version not in {1, PACK_FORMAT_VERSION}:
        raise ValueError('onbekend regiopackformaat; bouw een compatibel pack')
    extract = manifest.get('extract_format_version')
    if extract is not None and extract != EXTRACT_FORMAT_VERSION:
        raise ValueError('incompatibel extractformaat; reviewer moet caches en pack opnieuw bouwen')
    if manifest.get('gh_image') and manifest['gh_image'] != config.GRAPH_HOPPER_IMAGE:
        raise ValueError('GraphHopper-versie in het pack komt niet overeen')
    return {'legacy': version == 1, 'features': manifest.get('features'), 'built_at': manifest.get('built_at')}
