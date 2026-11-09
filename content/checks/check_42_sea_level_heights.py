"""Check 42: Fieldwork's sea-level heights at Manila's health facilities, against rasterio, SciPy and NumPy.

Fieldwork experiment 198 made the sea-level example's third workflow by hand: three published grids kept around Manila
by Raster input, sampled by Sample raster, combined by the workflow's own rules, and compared with the AR6 rise at
2100 by the published ruleset compare-level-to-elevation 1.0.0. It found 16 of 194 facilities on ground below that
level. The fixture is that chain run through Fieldwork's own functions, with the three windows the canvas sampled.

**Independent.** The windows are read here with rasterio. EGM2008 and DTU25MSS, published at grid nodes, are
interpolated with SciPy's RegularGridInterpolator over those nodes; DeltaDTM is the value of the cell rasterio's
index() gives. The nearest site is a haversine minimum in NumPy. The heights and the comparison are written out from
the fixture's declared arithmetic. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **At each AR6 site**, EGM2008 and DTU25MSS within 1e-9 m of SciPy's bilinear value; a site outside the window
   has none on either side.
2. **At each facility**, the ground height exactly rasterio's cell value, and the nearest site the same.
3. **Every height** (sea above the geoid, elevation) within 1e-9 m of the declared arithmetic on the values found here.
4. **Every level** (Reaches, StaysBelow) equal, and so the count of Reaches.

Recorded, not asserted: any facility within 1 mm of the projected level, where the two sides' rounding could fall
either way.

What this cannot establish: that a facility below the projected level will flood. There is no tide, surge, defence or
drainage here, and DeltaDTM is least certain at the coast (its stated error there is about 0.45 m). Nor that EGM2008's
cut is PROJ's whole grid: Fieldwork reads the same nodes from cdn.proj.org; its value at the gauge, 43.009 m, is
checked against pyproj in Fieldwork's own tests, since pyproj cannot share this kernel with rasterio.

Design record: fieldwork/docs/experiments/198-a-published-grid-read-at-points.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy
import rasterio
import scipy
from scipy.interpolate import RegularGridInterpolator

from .fixtures import load_fixture, verified_asset

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "sea-level-heights-manila-001.json"
RESULT = HERE.parent / "results" / "check-42-sea-level-heights.json"
EARTH_RADIUS_M = 6371008.8


def grid(path: pathlib.Path, fixture: dict):
    verified_asset(fixture, path)
    source = rasterio.open(path)
    values = source.read(1).astype("float64")
    return source, values


def bilinear(source, values):
    """SciPy over the nodes, which are the centres of the cells the window is written as."""
    rows, cols = values.shape
    t = source.transform
    lons = t.c + (numpy.arange(cols) + 0.5) * t.a
    lats = t.f + (numpy.arange(rows) + 0.5) * t.e
    # RegularGridInterpolator wants ascending axes; the window is north first.
    interpolate = RegularGridInterpolator((lats[::-1], lons), values[::-1, :], method="linear", bounds_error=True)

    def at(lon: float, lat: float) -> float | None:
        # OUTSIDE THE NODES, NO VALUE: a point without four nodes around it is outside the window, as Fieldwork says.
        if not (lats.min() <= lat <= lats.max() and lons.min() <= lon <= lons.max()):
            return None
        return float(interpolate([lat, lon])[0])
    return at


def haversine(lon1, lat1, lon2, lat2):
    p1, p2 = numpy.radians(lat1), numpy.radians(lat2)
    a = numpy.sin((p2 - p1) / 2) ** 2 + numpy.cos(p1) * numpy.cos(p2) * numpy.sin(numpy.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * numpy.arcsin(numpy.sqrt(a))


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    folder = fixture_path.parent
    egm_src, egm = grid(folder / "egm2008-window.tif", fixture)
    dtu_src, dtu = grid(folder / "dtu25mss-window.tif", fixture)
    dtm_src, dtm = grid(folder / "deltadtm-window.tif", fixture)
    egm_at, dtu_at = bilinear(egm_src, egm), bilinear(dtu_src, dtu)

    sites = []
    for s in fixture["input"]["sites"]:
        lon, lat = s["position"]
        mine = {"egm2008M": egm_at(lon, lat), "mssM": dtu_at(lon, lat)}
        sites.append({"site_id": s["site_id"], "position": s["position"], "scipy": mine,
                      "fieldwork": {"egm2008M": s["egm2008M"], "mssM": s["mssM"]},
                      "agrees": all((s[k] is None and mine[k] is None) or (s[k] is not None and mine[k] is not None
                                     and abs(s[k] - mine[k]) <= 1e-9) for k in mine)})
    by_site = {s["site_id"]: s["scipy"] for s in sites}
    site_ids = [s["site_id"] for s in fixture["input"]["sites"]]
    site_lon = numpy.array([s["position"][0] for s in fixture["input"]["sites"]])
    site_lat = numpy.array([s["position"][1] for s in fixture["input"]["sites"]])

    facilities, differs, close = [], [], []
    for f in fixture["output"]["facilities"]:
        lon, lat = f["position"]
        row, col = dtm_src.index(lon, lat)
        ground = float(dtm[row, col])
        nearest = site_ids[int(numpy.argmin(haversine(lon, lat, site_lon, site_lat)))]
        site = by_site[nearest]
        sea = site["mssM"] - site["egm2008M"]
        elevation = ground - sea - 0.037
        margin = elevation * 1000 - f["valueMm"]
        level = "Reaches" if margin <= 0 else "StaysBelow"
        problems = []
        if f["groundM"] != ground: problems.append(f"ground {f['groundM']} != {ground}")
        if f["nearestSite"] != nearest: problems.append(f"nearest {f['nearestSite']} != {nearest}")
        if abs(f["seaAboveGeoidM"] - sea) > 1e-9: problems.append(f"sea above geoid {f['seaAboveGeoidM']} != {sea}")
        if abs(f["elevationM"] - elevation) > 1e-9: problems.append(f"elevation {f['elevationM']} != {elevation}")
        if f["level"] != level: problems.append(f"level {f['level']} != {level}")
        if abs(margin) < 1: close.append({"id": f["id"], "marginMm": margin})
        if problems: differs.append({"id": f["id"], "problems": problems})
        facilities.append(level)

    reaches = facilities.count("Reaches")
    agrees = all(s["agrees"] for s in sites) and not differs and reaches == fixture["output"]["reaches"]
    manila = next(s for s in sites if s["site_id"] == "145")
    return {
        "check": "42-sea-level-heights",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": agrees,
        "criteria": "EGM2008 and DTU25MSS at each AR6 site within 1e-9 m of SciPy's bilinear value over the nodes; each "
                    "facility's ground exactly rasterio's cell, its nearest site the haversine minimum; every height within "
                    "1e-9 m of the declared arithmetic; every level equal, and the count of Reaches",
        "sites": sites,
        "manila": {"egm2008M": manila["scipy"]["egm2008M"], "mssM": manila["scipy"]["mssM"],
                   "seaAboveGeoidM": manila["scipy"]["mssM"] - manila["scipy"]["egm2008M"]},
        "facilities": len(facilities), "reaches": reaches, "fieldworkReaches": fixture["output"]["reaches"],
        "differs": differs, "withinOneMillimetre": close,
        "notEstablished": [
            "That a facility below the projected level will flood: no tide, surge, defence or drainage, and DeltaDTM is least certain at the coast.",
            "That the EGM2008 cut is PROJ's whole grid; its value at the gauge is checked against pyproj in Fieldwork's tests.",
            "That OpenStreetMap's 194 facilities are all the facilities there are.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__,
                        "scipy": scipy.__version__, "numpy": numpy.__version__,
                        "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
