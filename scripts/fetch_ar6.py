#!/usr/bin/env python3
"""Fetch only the AR6 confidence-output members this project needs, by HTTP range.

The archives are 9.24 GB and 8.75 GB; the members needed total about 440 MB. Zenodo honours
Range on its API URLs, so the central directory is read from the tail and only the wanted
members are pulled. Nothing large is ever stored.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from remote_zip import open_remote_zip, extract_member_fast

BASE = 'https://zenodo.org/api/records/6382554/files/{}/content'
ARCHIVES = {
    'vlm':   ('ar6-regional-confidence.zip',        'ar6-regional-confidence/regional'),
    'novlm': ('ar6-regional_novlm-confidence.zip',  'ar6-regional_novlm-confidence/regional_novlm'),
}
SCENARIOS = ('ssp126', 'ssp245', 'ssp585')
CACHE = pathlib.Path(__file__).parent.parent / '.cache' / 'ar6'

def member(root, scenario):
    return f'{root}/confidence_output_files/medium_confidence/{scenario}/total_{scenario}_medium_confidence_values.nc'

def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    for family, (archive, root) in ARCHIVES.items():
        url = BASE.format(archive)
        zf = None
        for scenario in SCENARIOS:
            out = CACHE / f'{family}_{scenario}.nc'
            if out.exists() and out.stat().st_size > 0:
                print(f'have    {out.name} ({out.stat().st_size/1e6:.1f} MB)', flush=True)
                continue
            zf = zf or open_remote_zip(url)
            name = member(root, scenario)
            print(f'fetch   {out.name} from {archive}', flush=True)
            size = extract_member_fast(url, name, out, zinfo=zf.getinfo(name))
            print(f'wrote   {out.name} ({size/1e6:.1f} MB)', flush=True)

if __name__ == '__main__':
    main()
