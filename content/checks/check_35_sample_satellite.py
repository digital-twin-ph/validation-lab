"""Check 35: Fieldwork Sample satellite files at points, against h5py and pyproj.

Fieldwork's Sample satellite files at points reads a Sentinel-5P Level 2 NetCDF file in the browser with h5wasm and
writes one row per point per overpass: the value of the pixel whose centre is nearest the point, its quality, and,
where there is no usable value, which kind of gap. The NYC worked example reads the four NO2 monitors this way.
Fieldwork experiment 179.

**Genuinely independent of the reading.** h5py is a separate HDF5 binding by separate authors; Fieldwork's h5wasm is
the HDF Group's C library compiled to WebAssembly. Both sit on libhdf5, so a defect in libhdf5 itself would be shared.
What differs is everything Fieldwork wrote: which chunks it reads, in what order, when it stops looking, and which
pixel it keeps. Here the whole swath is read at once and every centre is compared, so a point Fieldwork's chunk-by-chunk
search places on the wrong pixel, or stops looking for too early, disagrees.

**Which pixel is nearest is Fieldwork's declared rule, restated.** The distance is in degrees with the longitude scaled
by the cosine of the point's latitude, which is an approximation. So the pixel is recomputed from that statement, and
separately the geodesically nearest centre is found with pyproj.Geod and reported: it is a measurement of the
approximation, not part of the criterion.

Criteria, fixed before running:

1. Every point placed or not placed as the declared rule says, on the same pixel (scanline, ground pixel).
2. At every placed pixel, the value, the stored qa_value and the scanline time exactly h5py's.
3. For both quality operators, every row of the table rebuilt from the declared rule: the same rows in the same order,
   with the same gap kind, passes_quality, value_as_read, qa_value and value.

What this cannot establish: anything about a real orbit file's content, the reading of a remote file by HTTP range,
or whether the nearest centre is the right pixel for a study.
"""
import hashlib
import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import h5py
import numpy as np
import pyproj

from .fixtures import load_fixture, verified_asset

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "sample-satellite-s5p-001.json"
RESULT = HERE.parent / "results" / "check-35-sample-satellite.json"

FILL = 9e36
QA_FILL = 255
OFF_SWATH_FACTOR, OFF_SWATH_FLOOR = 1.5, 0.01


def declared_pixel(lon, lat, lats, lons):
    """The declared rule, written here from its statement rather than imported: the nearest valid centre by
    cos(lat)-scaled degrees, and no pixel when it is farther than the off-swath margin."""
    valid = (np.abs(lats) <= 90) & (np.abs(lons) <= 180)
    k = math.cos(math.radians(lat))
    d2 = np.where(valid, ((lons - lon) * k) ** 2 + (lats - lat) ** 2, np.inf)
    r, c = np.unravel_index(int(np.argmin(d2)), d2.shape)
    distance = math.sqrt(float(d2[r, c]))
    yc, xc, kc = float(lats[r, c]), float(lons[r, c]), math.cos(math.radians(float(lats[r, c])))
    spacing = math.inf
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < lats.shape[0] and 0 <= cc < lats.shape[1] and valid[rr, cc]:
            spacing = min(spacing, math.hypot((float(lons[rr, cc]) - xc) * kc, float(lats[rr, cc]) - yc))
    half = spacing / 2 if math.isfinite(spacing) else 0
    if distance > max(half * OFF_SWATH_FACTOR, OFF_SWATH_FLOOR):
        return None
    return int(r), int(c)


def geodesic_pixel(lon, lat, lats, lons, geod):
    """The geodesically nearest centre on WGS84, for the measurement, not the criterion."""
    flat_lat, flat_lon = lats.ravel().astype(float), lons.ravel().astype(float)
    _, _, dist = geod.inv(np.full(flat_lat.shape, lon), np.full(flat_lat.shape, lat), flat_lon, flat_lat)
    i = int(np.argmin(dist))
    return [int(i // lats.shape[1]), int(i % lats.shape[1])]


def rows_for(points, pixels, values, qas, times, scale, operator, threshold, declared, days, column):
    """Both cases' rows, rebuilt from the declared table rule."""
    raw = round(threshold / scale)
    out = []
    for p in points:
        for day in days:
            if day != declared["fileDate"]:
                out.append({"point_id": p["id"], "point": p["name"], "date": day, "overpass_time": "", "stream": "",
                            "orbit": "", "scanline": "", "ground_pixel": "", "value_as_read": "", "qa_value": "",
                            "passes_quality": "", "gap": "no overpass", "measure": column, "value": None})
                continue
            px = pixels[p["id"]]
            if px is None:
                # Not covered by a file that was read: the row names the file by its own time, stream and orbit.
                gap, passes, read, qa, time, r, c = "no overpass", None, None, None, declared["fileDatetime"], "", ""
            else:
                r, c = px
                v, qa, time = values[r, c], int(qas[r, c]), times[r]
                read = float(v) if math.isfinite(float(v)) and float(v) < FILL else None
                if read is None or qa == QA_FILL:
                    gap, passes = "no retrieval", None
                else:
                    passes = qa >= raw if operator == ">=" else qa > raw
                    gap = None if passes else "below quality threshold"
            out.append({"point_id": p["id"], "point": p["name"], "date": day,
                        "overpass_time": time or "", "stream": declared["stream"], "orbit": str(declared["orbit"]),
                        "scanline": "" if px is None else str(r), "ground_pixel": "" if px is None else str(c),
                        "value_as_read": "" if read is None else read,
                        "qa_value": "" if px is None or qa == QA_FILL else f"{qa * scale:.2f}",
                        "passes_quality": "" if passes is None else ("yes" if passes else "no"),
                        "gap": gap or "", "measure": column, "value": None if gap else read})
    return out


def same_row(fw, ours):
    """Field by field; value_as_read is a number written as text by Fieldwork, compared as a number."""
    differing = []
    for key, expected in ours.items():
        got = fw.get(key)
        if key == "value_as_read" and expected != "":
            if got == "" or float(got) != expected:
                differing.append(key)
        elif got != expected:
            differing.append(key)
    return differing


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    p = fixture["declaredParameters"]
    nc = fixture_path.parent / p["file"]
    raw = verified_asset(fixture, nc)
    with h5py.File(nc, "r") as f:
        lats = f[p["paths"]["latitude"]][0]
        lons = f[p["paths"]["longitude"]][0]
        values = f[p["paths"]["value"]][0]
        qas = f[p["paths"]["quality"]][0]
        scale = float(np.asarray(f[p["paths"]["quality"]].attrs["scale_factor"]).ravel()[0])
        times = [t.decode() if isinstance(t, bytes) else str(t) for t in f[p["paths"]["time"]][0]]
        chunks = f[p["paths"]["latitude"]].chunks
    geod = pyproj.Geod(ellps="WGS84")
    points = fixture["input"]["points"]
    fw_pixels = {x["pointId"]: x for x in fixture["output"]["pixels"]}

    pixels, placement, geodesic = {}, [], []
    for pt in points:
        ours = declared_pixel(pt["lon"], pt["lat"], lats, lons)
        pixels[pt["id"]] = ours
        fw = fw_pixels[pt["id"]]
        theirs = None if fw["row"] is None else (fw["row"], fw["col"])
        read_ok = True
        if ours is not None:
            r, c = ours
            v = float(values[r, c])
            expected_value = v if v < FILL else None
            read_ok = (fw["value"] == expected_value and fw["qaRaw"] == int(qas[r, c]) and fw["time"] == times[r])
        placement.append({"point": pt["id"], "fieldwork": theirs and list(theirs), "declaredRule": ours and list(ours),
                          "samePixel": theirs == ours, "valueQualityTimeAgree": read_ok})
        if ours is not None:
            g = geodesic_pixel(pt["lon"], pt["lat"], lats, lons, geod)
            geodesic.append({"point": pt["id"], "declaredRule": list(ours), "geodesic": g, "same": g == list(ours)})

    days = []
    d = datetime.fromisoformat(p["from"])
    while d <= datetime.fromisoformat(p["until"]):
        days.append(d.date().isoformat())
        d = datetime.fromordinal(d.toordinal() + 1)
    column = p["paths"]["value"].split("/")[-1]
    cases = []
    for case in fixture["output"]["cases"]:
        ours = rows_for(points, pixels, values, qas, times, scale, case["operator"], p["quality"]["threshold"],
                        p, days, column)
        theirs = case["rows"]
        differing = [{"row": i + 1, "fields": f} for i, (a, b) in enumerate(zip(theirs, ours)) if (f := same_row(a, b))]
        counts = {"passing": sum(1 for r in ours if r["passes_quality"] == "yes"),
                  "belowQuality": sum(1 for r in ours if r["gap"] == "below quality threshold"),
                  "noRetrieval": sum(1 for r in ours if r["gap"] == "no retrieval"),
                  "noOverpass": sum(1 for r in ours if r["gap"] == "no overpass")}
        cases.append({"operator": case["operator"], "rows": {"fieldwork": len(theirs), "rebuilt": len(ours)},
                      "counts": {"fieldwork": {k: case["counts"][k] for k in counts}, "rebuilt": counts},
                      "rowsDiffering": differing,
                      "agrees": len(theirs) == len(ours) and not differing})

    placement_agrees = all(x["samePixel"] and x["valueQualityTimeAgree"] for x in placement)
    return {
        "check": "35-sample-satellite",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {"runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
                        "isPyodide": sys.platform == "emscripten", "h5py": h5py.__version__,
                        "hdf5": h5py.version.hdf5_version, "numpy": np.__version__, "pyproj": pyproj.__version__},
        "fixture": {"id": fixture.get("fixtureId"), "sha256": digest, "fileSHA256": hashlib.sha256(raw).hexdigest(),
                    "application": fixture["application"], "operation": fixture["operation"]},
        "file": {"shape": list(lats.shape), "chunks": list(chunks) if chunks else None, "qaScale": scale},
        "criterion": "every point placed or not as the declared rule says, on the same pixel; value, stored qa_value "
                     "and scanline time exactly h5py's there; for both operators every table row rebuilt from the "
                     "declared rule, field by field",
        "placement": placement,
        "placementAgrees": placement_agrees,
        "geodesic": {"note": "The geodesically nearest centre (pyproj.Geod, WGS84), against the declared cos(lat)-scaled "
                             "rule. A measurement of the approximation, not part of the criterion.",
                     "points": geodesic, "same": sum(1 for g in geodesic if g["same"]), "of": len(geodesic)},
        "cases": cases,
        "notEstablished": ["Anything about a real orbit file's content: the file is synthetic.",
                           "Reading a remote file by HTTP range, which is where the cost is.",
                           "Whether the nearest centre is the right pixel for a study.",
                           "A defect in libhdf5 itself, which h5py and h5wasm share."],
        "agrees": placement_agrees and all(c["agrees"] for c in cases),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for x in result["placement"]:
        ok = x["samePixel"] and x["valueQualityTimeAgree"]
        print(f"{'OK ' if ok else 'DIFF'} {x['point']:<16} fieldwork {x['fieldwork']}  declared {x['declaredRule']}")
    g = result["geodesic"]
    print(f"geodesic nearest = declared rule at {g['same']} of {g['of']} placed points")
    for c in result["cases"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} qa_value {c['operator']} 0.75: {c['rows']['fieldwork']} rows, "
              f"{c['counts']['fieldwork']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
