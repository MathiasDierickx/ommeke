"""Provenance en compatibiliteit van lokale regiopacks."""
import hashlib
import json
import pickle
from datetime import datetime, UTC
from . import config
from .osm import EXTRACT_FORMAT_VERSION

PACK_FORMAT_VERSION = 2
# Verhoog bij elke wijziging van routingprofielen, custom models of GraphHopper-config
# die bestaande packs onbruikbaar maakt; oudere packs zonder veld blijven geldig.
PROFILE_CONFIG_VERSION = 1


def _source_data_date(region, extract_source):
    """Peildatum van de brondata: de gedownloade PBF, anders de extractcache."""
    for basis, path in (('pbf', region.data / region.pbf_name), ('extract_cache', extract_source)):
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat(), basis
    return None, None


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
    source_date, source_basis = _source_data_date(region, source)
    gh_config = region.gh_dir / 'config.yml'
    return {
        'pack_format_version': PACK_FORMAT_VERSION,
        'source_data_date': source_date,
        'source_data_basis': source_basis,
        'routing_profile': config.GH_PROFILE,
        'profile_config_version': PROFILE_CONFIG_VERSION,
        'gh_config_sha256': hashlib.sha256(gh_config.read_bytes()).hexdigest() if gh_config.exists() else None,
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
    profile = manifest.get('profile_config_version')
    if profile is not None and profile != PROFILE_CONFIG_VERSION:
        raise ValueError('incompatibele profielconfiguratie in het pack; reviewer moet het pack opnieuw bouwen '
                         '(zie docs/OPERATIONS.md, Pack herbouwen)')
    return {'legacy': version == 1, 'features': manifest.get('features'), 'built_at': manifest.get('built_at'),
            'source_data_date': manifest.get('source_data_date'),
            'profile_config_version': profile}


def describe(manifest):
    """Nederlandstalige samenvatting van features en versies; ontbrekende velden zijn None."""
    features = manifest.get('features') or {}
    return {
        'slug': manifest.get('slug'),
        'packformaat': manifest.get('pack_format_version', 1),
        'legacy': manifest.get('pack_format_version', 1) == 1,
        'gebouwd_op': manifest.get('built_at'),
        'brondata_datum': manifest.get('source_data_date'),
        'brondata_basis': manifest.get('source_data_basis'),
        'extractformaat': manifest.get('extract_format_version'),
        'graphhopper_image': manifest.get('gh_image'),
        'routingprofiel': manifest.get('routing_profile'),
        'profielconfig_versie': manifest.get('profile_config_version'),
        'gh_config_sha256': manifest.get('gh_config_sha256'),
        'modelhashes': manifest.get('model_sha256'),
        'features': {
            'waterlopen': features.get('waterways'),
            'landmarks': features.get('landmarks'),
            'gebieden': features.get('areas'),
            'persoonlijke_heat': manifest.get('contains_personal_heat'),
        },
    }


def read_pack_json(pack):
    """Lees uitsluitend pack.json uit een tar.gz, zonder uit te pakken."""
    import tarfile
    with tarfile.open(pack, 'r:gz') as archive:
        try:
            handle = archive.extractfile('pack.json')
        except KeyError:
            handle = None
        if handle is None:
            raise ValueError('regiopack mist pack.json')
        return json.load(handle)


def installed_summary(region):
    """Beschrijving van het uitgepakte pack van een regio, of None als er geen pack.json is."""
    path = region.root / 'pack.json'
    if not path.is_file():
        return None
    return describe(json.loads(path.read_text()))
