#!/usr/bin/env python3
"""Extract a bounded AR6 relative sea-level projection for Philippine tide-gauge sites.

What this reads and what it refuses to assume, all measured from the files rather than declared
in advance (see fieldwork docs/experiments/62 and the TODO entry of 2026-10-09):

  * `sea_level_change` is stored as int16 with `units: 'mm'`, `scale_factor` and a
    `_FillValue` of -32768. All three are read from the variable. A fill value becomes an EMPTY
    cell, never 0 and never the string "nan": a missing projection is unknown, and the host
    retains an empty cell as unknown while refusing a non-numeric value.
  * The file carries no scenario, family or confidence dimension. Those identify which file a
    row came from, so they are written as columns here and recorded in provenance as the
    selection that produced the extract.
  * The medium-confidence file is a **p-box** combining workflow p-boxes, named in the file's
    `source` attribute. It is NOT a single workflow, so no workflow id is claimed. A value read
    from it is a bound on a quantile across the combined workflows.
  * AR6 derives a likely range (17th-83rd) from medium confidence and states it cannot derive a
    very likely range (5th-95th). Only the median and the likely range are extracted; the file
    offers all 107 quantiles including 0.0 and 1.0, which must not be read as a range.
  * No file attribute carries the baseline period. It is stated here from AR6 documentation and
    labelled as documentation-sourced, never inferred from the data.
"""
import csv, hashlib, json, pathlib, platform, sys
from datetime import datetime, timezone

import numpy as np
from netCDF4 import Dataset

LAB = pathlib.Path(__file__).parent.parent
CACHE = LAB / '.cache' / 'ar6'
SITES_CSV = LAB.parent / 'widget-pack-sea-level-rise' / 'examples' / 'manila-coastal-exposure' / 'projection-sites-ph.csv'

SCENARIOS = ('ssp126', 'ssp245', 'ssp585')
FAMILIES = {'vlm': 'with_vlm', 'novlm': 'without_vlm'}
YEARS = (2050, 2100)
QUANTILES = (0.17, 0.50, 0.83)          # median and the likely range AR6 supports
CONFIDENCE = 'medium'
BASELINE_PERIOD = '1995-2014'           # AR6 WG1 Chapter 9; not present in any file attribute

CITATIONS = [
    'Fox-Kemper, B., et al. 2021: Ocean, Cryosphere and Sea Level Change. In Climate Change 2021: '
    'The Physical Science Basis. IPCC AR6 WG1, Chapter 9. doi:10.1017/9781009157896.011',
    'Kopp, R. E., Garner, G. G., et al. 2023. The Framework for Assessing Changes To Sea-Level '
    '(FACTS) v1.0. Geoscientific Model Development 16, 7461-7489. doi:10.5194/gmd-16-7461-2023',
    'Garner, G. G., et al. 2021. IPCC AR6 Sea Level Projections. Version 20210809. '
    'doi:10.5281/zenodo.5914709',
]

def gauge_sites():
    """The published tide-gauge sites among the pack's Philippine subset.

    Gridded sites sit at whole degrees and are mostly open water. A tide gauge is also the only
    place where local mean sea level has a surveyed relationship to a national datum, which is
    what a later elevation comparison needs.
    """
    rows = list(csv.DictReader(SITES_CSV.open()))
    gauges = [r for r in rows
              if float(r['latitude']) != int(float(r['latitude']))
              or float(r['longitude']) != int(float(r['longitude']))]
    # Sabah gauges fall inside the bounding box but are not Philippine.
    malaysian = {'KOTA_KINABALU', 'LAHAT_DATU', 'SANDAKAN', 'TAWAU'}
    return [r for r in gauges if r['name'] not in malaysian]

def read_file(path, site_ids):
    """Read the wanted cells, honouring units, scale_factor and _FillValue."""
    ds = Dataset(path)
    var = ds.variables['sea_level_change']
    var.set_auto_mask(False)                       # read the sentinel, do not let it become NaN
    fill = int(var._FillValue)
    scale = float(getattr(var, 'scale_factor', 1.0))
    units = str(var.units)
    locations = {int(v): i for i, v in enumerate(ds.variables['locations'][:])}
    years = {int(v): i for i, v in enumerate(ds.variables['years'][:])}
    quantiles = ds.variables['quantiles'][:]
    meta = {'source': str(ds.source), 'description': str(ds.description), 'history': str(ds.history),
            'units': units, 'scale_factor': scale, 'fill_value': fill,
            'conventions': getattr(ds, 'Conventions', None),
            'dimensions': {k: int(v.size) for k, v in ds.dimensions.items()},
            'dtype': str(var.dtype)}
    out, missing = {}, 0
    for q in QUANTILES:
        hits = np.flatnonzero(quantiles == q)
        if not hits.size:
            raise SystemExit(f'{path.name}: quantile {q} is not published in this file')
        qi = int(hits[0])
        for year in YEARS:
            if year not in years:
                raise SystemExit(f'{path.name}: year {year} is not published in this file')
            yi = years[year]
            for site in site_ids:
                if site not in locations:
                    raise SystemExit(f'{path.name}: site {site} is not in this file')
                raw = int(var[qi, yi, locations[site]])
                if raw == fill:
                    out[(site, year, q)] = None     # unknown, written as an empty cell
                    missing += 1
                else:
                    out[(site, year, q)] = raw * scale
    ds.close()
    return out, meta, missing

def main():
    sites = gauge_sites()
    site_ids = [int(s['site_id']) for s in sites]
    print(f'sites: {len(sites)} published tide gauges -> ' + ', '.join(s['name'] for s in sites))

    rows, sources, missing_total = [], {}, 0
    for family_key, family_value in FAMILIES.items():
        for scenario in SCENARIOS:
            path = CACHE / f'{family_key}_{scenario}.nc'
            if not path.exists():
                raise SystemExit(f'missing {path}; run scripts/fetch_ar6.py first')
            values, meta, missing = read_file(path, site_ids)
            missing_total += missing
            sources[f'{family_key}/{scenario}'] = {
                **meta,
                'file': path.name,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'bytes': path.stat().st_size,
            }
            for (site, year, q), value in values.items():
                rows.append({'site_id': site, 'scenario': scenario, 'basis': CONFIDENCE,
                             'family': family_value, 'year': year, 'quantile': f'{q:g}',
                             'value_mm': '' if value is None else f'{value:g}'})

    rows.sort(key=lambda r: (r['site_id'], r['scenario'], r['family'], r['year'], r['quantile']))
    out_dir = LAB / 'content' / 'results'
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / 'ar6-philippines-gauges-extract.csv'
    # `basis` is the host's key component: it names which published derivation a value came from.
    # `basisKind` in provenance says what that name is — here a confidence level whose file is a
    # p-box over workflows, not a single workflow identifier.
    fields = ['site_id', 'scenario', 'basis', 'family', 'year', 'quantile', 'value_mm']
    with csv_path.open('w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)

    import netCDF4, xarray
    provenance = {
        'schema': 'fieldwork/pack-extract-provenance/2',
        'extractedAt': datetime.now(timezone.utc).isoformat(),
        'dataset': {'name': 'IPCC AR6 Sea Level Projections',
                    'conceptDOI': '10.5281/zenodo.5914709', 'versionDOI': '10.5281/zenodo.6382554',
                    'version': '20210809', 'licence': 'CC-BY-4.0', 'format': 'NetCDF4/HDF5'},
        'selection': {'sites': site_ids, 'siteKind': 'published tide gauges, Philippine',
                      'scenarios': list(SCENARIOS), 'confidence': CONFIDENCE,
                      'families': FAMILIES, 'years': list(YEARS), 'quantiles': list(QUANTILES)},
        'basis': {'column': 'basis', 'value': CONFIDENCE, 'basisKind': 'confidence-pbox',
                  'note': 'The basis column names the published derivation. Its kind is '
                          'confidence-pbox: the file is a p-box combining workflow p-boxes, so no '
                          'single workflow identifier would be true of it.'},
        'quantileBasis': {
            'kind': 'p-box bound',
            'note': 'The medium-confidence files are p-boxes combining workflow p-boxes, named in '
                    'each file\'s source attribute. A value is a bound on a quantile across the '
                    'combined workflows, not a quantile of one distribution, and no workflow id is '
                    'claimed. AR6 derives a likely range (17th-83rd) from medium confidence and '
                    'states it cannot derive a very likely range (5th-95th).',
            'extractedQuantiles': list(QUANTILES),
            'availableButNotExtracted': 'the file publishes 107 quantiles including 0.0 and 1.0; '
                                        'these are not a range and not a worst case'},
        'units': {'published': 'mm', 'inThisFile': 'mm', 'column': 'value_mm',
                  'note': 'Values are written as published. scale_factor is applied; the host '
                          'declares the unit on import and converts for comparison.'},
        'missingData': {'fillValue': -32768, 'cellsMissing': missing_total,
                        'note': 'A fill value is written as an empty cell. Never 0, never "nan".'},
        'baselinePeriod': {'value': BASELINE_PERIOD, 'source': 'AR6 WG1 Chapter 9 documentation',
                           'note': 'No file attribute carries the baseline period; it is stated '
                                   'from documentation and never inferred from the data.'},
        'sourceFiles': sources,
        'extract': {'file': csv_path.name, 'rows': len(rows),
                    'sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest()},
        'environment': {'kind': 'CPython', 'python': platform.python_version(),
                        'platform': platform.platform(),
                        'netCDF4': netCDF4.__version__, 'xarray': xarray.__version__,
                        'numpy': np.__version__,
                        'note': 'A CPython run is a different environment from the Pyodide kernel '
                                'the notebooks use and is labelled as such.'},
        'requiredCitations': CITATIONS,
        'notEstablished': [
            'that this extract preserves enough of the published uncertainty to be presented',
            'any statement about inundation, flooding or exposure',
            'that these values are comparable with an elevation on any datum other than the '
            'baseline sea surface',
        ],
    }
    json_path = out_dir / 'ar6-philippines-gauges-extract-provenance.json'
    json_path.write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'wrote {csv_path.relative_to(LAB)} ({len(rows)} rows, {missing_total} missing)')
    print(f'wrote {json_path.relative_to(LAB)}')

if __name__ == '__main__':
    main()
