#!/usr/bin/env python3
"""Build the bundled data for Fieldwork's Manila coastal exposure example.

Data preparation, not validation. It reads files this lab already produced or
redistributes, and writes the three JSON files the example imports. Nothing here
checks Fieldwork; nothing in Fieldwork runs this. Re-run it to rebuild the example
from source rather than editing the JSON by hand.

Inputs
  content/results/ar6-philippines-gauges-extract.csv   the AR6 extract this lab made
  ../widget-pack-sea-level-rise/examples/.../projection-sites-ph.csv   the published site list
(Facilities are no longer built here. The example carries them as the Find health
facilities widget retrieved them, so the stored provenance is the widget's own
rather than a relabelling of this script's output.)

Licences travel with the outputs: AR6 is CC-BY-4.0 and obliges three citations;
the facilities are OpenStreetMap-derived and ODbL, which is share-alike.
"""
import csv, json, math, pathlib, platform, sys
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent.parent
OUT = HERE.parent / 'fieldwork' / 'examples' / 'manila-sea-level'
SITES_CSV = HERE.parent / 'widget-pack-sea-level-rise' / 'examples' / 'manila-coastal-exposure' / 'projection-sites-ph.csv'
EXTRACT_CSV = HERE / 'content' / 'results' / 'ar6-philippines-gauges-extract.csv'

CITATIONS = [
    'Fox-Kemper, B., et al. 2021: Ocean, Cryosphere and Sea Level Change. In Climate Change 2021: '
    'The Physical Science Basis. IPCC AR6 WG1, Chapter 9. doi:10.1017/9781009157896.011',
    'Kopp, R. E., Garner, G. G., et al. 2023. The Framework for Assessing Changes To Sea-Level '
    '(FACTS) v1.0. Geoscientific Model Development 16, 7461-7489. doi:10.5194/gmd-16-7461-2023',
    'Garner, G. G., et al. 2021. IPCC AR6 Sea Level Projections. Version 20210809. '
    'doi:10.5281/zenodo.5914709',
]
# The study area for the exposure half. Manila only: the extract is national and the
# facilities are not, and pretending otherwise would overstate what the example shows.
MANILA = (120.93, 14.52, 121.05, 14.68)
KINDS = {'hospital', 'clinic'}
MAX_FACILITIES = 60


def rows(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(handle)]


def projections():
    """The extract as the shape Fieldwork's tabular import stores: a long-format table
    keyed on everything but the value, with the unit stated rather than assumed."""
    data = rows(EXTRACT_CSV)
    keys = ['site_id', 'scenario', 'basis', 'family', 'year', 'quantile']
    return {
        'kind': 'data-table', 'keys': keys, 'valueField': 'value_mm', 'unit': 'millimetre',
        'rows': [{'key': {k: r[k] for k in keys}, 'value': float(r['value_mm'])} for r in data],
        'rowCount': len(data), 'missingValueCount': 0,
    }


def sites(wanted):
    """Only the sites the extract actually covers. A site layer wider than the extract
    would offer assignments to sites that carry no projection."""
    found = [r for r in rows(SITES_CSV) if r['site_id'] in wanted]
    missing = wanted - {r['site_id'] for r in found}
    if missing:
        raise SystemExit(f'site list is missing ids present in the extract: {sorted(missing)}')
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': f"site-{r['site_id']}",
         'properties': {'name': r['name'].replace('_', ' ').title(), 'site_id': r['site_id']},
         'geometry': {'type': 'Point',
                      'coordinates': [float(r['longitude']), float(r['latitude'])]}}
        for r in sorted(found, key=lambda r: int(r['site_id']))]}


def facilities(path):
    """Real OpenStreetMap health facilities inside the Manila box, the same data the
    Find health facilities widget retrieves live. Bundled so the example runs with no
    network; a practitioner can replace this node with the live widget."""
    payload = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    kept = []
    for feature in payload['features']:
        props, geom = feature.get('properties') or {}, feature.get('geometry') or {}
        kind = (props.get('healthcare') or props.get('amenity') or '').strip()
        name = (props.get('name') or '').strip()
        coords = geom.get('coordinates')
        if kind not in KINDS or not name or not coords:
            continue
        x, y = float(coords[0]), float(coords[1])
        if not (MANILA[0] <= x <= MANILA[2] and MANILA[1] <= y <= MANILA[3]):
            continue
        kept.append({'type': 'Feature',
                     'id': f"{str(props.get('osm_type','node')).rstrip('s')}-{props.get('osm_id')}",
                     'properties': {'name': name, 'kind': kind},
                     'geometry': {'type': 'Point', 'coordinates': [x, y]}})
    kept.sort(key=lambda f: f['properties']['name'])
    if len(kept) > MAX_FACILITIES:
        # Evenly spaced through the sorted list rather than the first N, so the sample is
        # not all one alphabetical corner of the city.
        step = len(kept) / MAX_FACILITIES
        kept = [kept[int(i * step)] for i in range(MAX_FACILITIES)]
    return {'type': 'FeatureCollection', 'features': kept}


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: build_sea_level_example.py <hotosm_phl_health_facilities.geojson>')
    OUT.mkdir(parents=True, exist_ok=True)
    table = projections()
    wanted = {r['key']['site_id'] for r in table['rows']}
    site_layer = sites(wanted)
    facility_layer = facilities(sys.argv[1])
    (OUT / 'projections.json').write_text(json.dumps(table, indent=1) + '\n')
    (OUT / 'sites.json').write_text(json.dumps(site_layer, indent=1) + '\n')
    (OUT / 'facilities.json').write_text(json.dumps(facility_layer, indent=1) + '\n')
    (OUT / 'provenance.json').write_text(json.dumps({
        'builtAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'builtBy': 'validation-lab/scripts/build_sea_level_example.py',
        'environment': {'kind': 'CPython', 'python': platform.python_version(),
                        'platform': platform.platform(), 'isPyodide': False},
        'projections': {
            'source': 'IPCC AR6 Sea Level Projections', 'datasetIRI': 'https://doi.org/10.5281/zenodo.5914709',
            'datasetVersion': '20210809', 'licence': 'CC-BY-4.0', 'requiredCitations': CITATIONS,
            'baselinePeriod': '1995-2014', 'unit': 'millimetre', 'basisKind': 'confidence-pbox',
            'values': table['rowCount'], 'sites': sorted(wanted, key=int),
            'note': 'Extracted by validation-lab/scripts/extract_ar6_philippines.py. basis is a '
                    'confidence level, not a workflow: the AR6 confidence output files are p-boxes '
                    'over several workflows and carry no workflow dimension.'},
        'sites': {'source': 'IPCC AR6 projection site list', 'licence': 'CC-BY-4.0',
                  'count': len(site_layer['features'])},
        'facilities': {'source': 'OpenStreetMap, Humanitarian OpenStreetMap Team country export',
                       'licence': 'ODbL-1.0',
                       'attribution': '© OpenStreetMap contributors, Open Database License (ODbL) 1.0',
                       'kinds': sorted(KINDS), 'boundingBox': list(MANILA),
                       'count': len(facility_layer['features']),
                       'note': 'A sample of the facilities inside the box, evenly spaced through '
                               'the name-sorted list. Not a facility register and not complete: '
                               'OpenStreetMap states no completeness, so an absence here is not '
                               'evidence of absence on the ground.'},
    }, indent=1) + '\n')
    print(f'projections {table["rowCount"]} values over {len(wanted)} sites')
    print(f'sites       {len(site_layer["features"])}')
    print(f'facilities  {len(facility_layer["features"])}')
    print(f'written to  {OUT}')


if __name__ == '__main__':
    main()
