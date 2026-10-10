#!/usr/bin/env python3
"""Fetch health facilities near a published tide gauge from healthsites.io.

Licence: the healthsites.io database is ODbL (confirmed in the project's own LICENSE-DATA.txt),
and is OpenStreetMap-derived. ODbL permits redistribution, unlike GADM, but attaches
**share-alike** to a derivative database: an extract redistributed with the pack must itself be
offered under ODbL and must attribute healthsites.io and OpenStreetMap contributors. This script
writes that obligation into the provenance beside the data, so the file cannot travel without it.

The API key is read from fieldwork/.secrets/ and never printed, logged or placed in a URL that
is echoed. Requests are paged and bounded: the key carries a site-wide daily quota that the
caller does not control.
"""
import csv, hashlib, json, math, pathlib, platform, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

LAB = pathlib.Path(__file__).parent.parent
KEY_FILE = LAB.parent / 'fieldwork' / '.secrets' / 'healthsites_api_key'
API = 'https://healthsites.io/api/v3/facilities/'
PAGE_SIZE = 100
MAX_PAGES = 12                       # a bound on quota spend, not a belief about the data

# The population a coastal exposure review is about. Pharmacies and dentists dominate the raw
# extract and are not the facilities such a review concerns.
KINDS = ('hospital', 'clinic')

GAUGES = {'MANILA': (14.58, 120.97), 'JOLO': (6.07, 121.00), 'DAVAO': (7.08, 125.63)}

ATTRIBUTION = ('Health facility data © healthsites.io contributors and © OpenStreetMap '
               'contributors, available under the Open Database License (ODbL). '
               'https://healthsites.io  https://www.openstreetmap.org/copyright')


def bbox(lat, lon, radius_m):
    dy = radius_m / 111195
    dx = radius_m / (111195 * math.cos(math.radians(lat)))
    return f'{lon-dx:.5f},{lat-dy:.5f},{lon+dx:.5f},{lat+dy:.5f}'


def fetch_page(key, extent, page):
    query = urllib.parse.urlencode({'api-key': key, 'extent': extent, 'page': page})
    request = urllib.request.Request(f'{API}?{query}', headers={'User-Agent': 'fieldwork-validation-lab/0.1'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except Exception as error:                       # noqa: BLE001 - the URL carries the key
            if attempt == 3:
                raise SystemExit(f'healthsites request failed on page {page}: {type(error).__name__}')
            time.sleep(3 * (attempt + 1))


def main():
    gauge = sys.argv[1] if len(sys.argv) > 1 else 'MANILA'
    radius_m = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    if gauge not in GAUGES:
        raise SystemExit(f'unknown gauge {gauge}; known: {", ".join(GAUGES)}')
    if not KEY_FILE.exists():
        raise SystemExit(f'no API key at {KEY_FILE}')
    key = KEY_FILE.read_text().strip()

    lat, lon = GAUGES[gauge]
    extent = bbox(lat, lon, radius_m)
    raw, pages = [], 0
    while pages < MAX_PAGES:
        page = fetch_page(key, extent, pages + 1)
        pages += 1
        if not page:
            break
        raw.extend(page)
        print(f'page {pages}: {len(page)} records', flush=True)
        if len(page) < PAGE_SIZE:
            break
    truncated = pages >= MAX_PAGES and len(raw) % PAGE_SIZE == 0

    kept = []
    for item in raw:
        attributes = item.get('attributes') or {}
        kind = attributes.get('healthcare') or attributes.get('amenity')
        centroid = item.get('centroid') or {}
        coordinates = centroid.get('coordinates')
        name = (attributes.get('name') or '').strip()
        if kind not in KINDS or not coordinates or not name:
            continue
        kept.append({'id': f"{item.get('osm_type')}/{item.get('osm_id')}", 'name': name, 'kind': kind,
                     'longitude': round(float(coordinates[0]), 6), 'latitude': round(float(coordinates[1]), 6),
                     'completeness': item.get('completeness')})
    kept.sort(key=lambda r: (r['kind'], r['name']))

    out_dir = LAB / 'content' / 'results'
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f'healthsites-{gauge.lower()}-{radius_m}m'
    csv_path = out_dir / f'{stem}.csv'
    fields = ['id', 'name', 'kind', 'latitude', 'longitude', 'completeness']
    with csv_path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader(); writer.writerows(kept)

    provenance = {
        'schema': 'fieldwork/facility-extract-provenance/1',
        'retrievedAt': datetime.now(timezone.utc).isoformat(),
        'source': {'name': 'healthsites.io', 'endpoint': API, 'apiVersion': 'v3',
                   'derivedFrom': 'OpenStreetMap',
                   'licence': 'ODbL', 'licenceUrl': 'https://opendatacommons.org/licenses/odbl/',
                   'attribution': ATTRIBUTION,
                   'shareAlike': ('ODbL attaches share-alike to a derivative database. An extract '
                                  'redistributed with a pack must be offered under ODbL and carry this '
                                  'attribution. A rendered map is a Produced Work and needs attribution '
                                  'only.')},
        'selection': {'gauge': gauge, 'gaugeLatLon': [lat, lon], 'radiusMetres': radius_m,
                      'extent': extent, 'kindsKept': list(KINDS),
                      'note': ('The extent is a lon/lat box around the gauge, so a corner is farther than '
                               'the radius. The study area itself is the circle, applied in the workflow.')},
        'counts': {'returned': len(raw), 'pagesFetched': pages, 'kept': len(kept),
                   'droppedNotRequestedKind': sum(1 for i in raw
                        if ((i.get('attributes') or {}).get('healthcare')
                            or (i.get('attributes') or {}).get('amenity')) not in KINDS),
                   'droppedNoCoordinates': sum(1 for i in raw if not (i.get('centroid') or {}).get('coordinates')),
                   'droppedNoName': sum(1 for i in raw if not ((i.get('attributes') or {}).get('name') or '').strip())},
        'truncated': truncated,
        'extract': {'file': csv_path.name, 'rows': len(kept),
                    'sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest()},
        'environment': {'kind': 'CPython', 'python': platform.python_version(), 'platform': platform.platform()},
        'notEstablished': [
            'that this is a complete list of facilities in the area',
            'that any facility is operating, or offers the service its tags imply',
            'that an elevation at a facility point represents the building',
        ],
    }
    json_path = out_dir / f'{stem}-provenance.json'
    json_path.write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'wrote {csv_path.relative_to(LAB)} ({len(kept)} of {len(raw)} records kept)')
    print(f'wrote {json_path.relative_to(LAB)}')
    if truncated:
        print('WARNING: the page bound was reached; the extract may be incomplete.')


if __name__ == '__main__':
    main()
