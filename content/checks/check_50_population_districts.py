"""Check 50: three population models totalled over Rwanda's and Botswana's census districts, against rasterio.

Fieldwork experiment 209. WorldPop 2025, GRID3 2025 and GHS-POP 2025, each totalled over the 30 districts of Rwanda and
the 28 of Botswana by Sample a raster over areas, and each district's share of its source's total set beside the 2022
census. Fieldwork's own test compared the shares rounded to 0.1 %. Here every district's total and cell count is
recomputed, unrounded, from the same files.

**The rasters are not in this repository**, nor in the example's: tens of megabytes each. The fixture carries each
file's address, size and digest; this check reads the files from the folder named by POP_FILES and verifies each digest
before reading a cell. Without that folder it says so and does not run: the browser kernel cannot hold these files.

**Independent.** rasterio reads each raster whole; `rasterio.features.geometry_mask` (GDAL's rasterizer, all_touched
off: a cell is in when its centre is) marks each district's cells; NumPy sums them in float64. The boundaries are read
from their GeoJSON with the standard library. The census shares are recomputed from the census CSV. Nothing here reads
Fieldwork's code.

Criteria, fixed before running:

1. **Cells**: each district's count of cells with a value, from each source, equal.
2. **Totals**: each district's total within 1e-9 of rasterio's, relative (both sum float32 cells in float64, in
   different orders).
3. **Shares**: each district's share of its source's total within 1e-12, and the census shares from the CSV.

What this cannot establish: that any source is right; that a cell whose centre falls exactly on a shared border belongs
to one district rather than both (Fieldwork counts it in both; GDAL in one; any difference is reported, by district);
that GHS-POP's window, cut from the global file, is the window Fieldwork reads by range (a separate Fieldwork test).

Design record: fieldwork/docs/experiments/209-three-population-rasters-and-the-census.md
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy
import rasterio
from rasterio.features import geometry_mask

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "population-districts-001.json"
RESULT = HERE.parent / "results" / "check-50-population-districts.json"
EXAMPLE = HERE.parents[2] / "example-population-models-census"
SOURCES = ["WorldPop", "GRID3", "GHS-POP"]
CENSUS = {"RWA": "rwanda_census_2022_districts.csv", "BWA": "botswana_census_2022_districts.csv"}


def verified(folder: pathlib.Path, item: dict) -> pathlib.Path:
    path = folder / item["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item["sha256"]:
        raise ValueError(f"{item['path']} has digest {digest[:12]}, not {item['sha256'][:12]}: not read")
    return path


def totals_over(raster: pathlib.Path, districts: list[dict]) -> dict:
    with rasterio.open(raster) as r:
        cells = r.read(1, masked=False).astype(numpy.float64)
        nodata, transform, shape = r.nodata, r.transform, (r.height, r.width)
    valid = numpy.isfinite(cells)
    if nodata is not None:
        valid &= cells != nodata
    out = {}
    for d in districts:
        inside = ~geometry_mask([d["geometry"]], out_shape=shape, transform=transform, all_touched=False)
        mine = inside & valid
        out[d["name"]] = {"total": float(cells[mine].sum()), "cells": int(mine.sum()),
                          "noData": int((inside & ~valid).sum())}
    return out


def run(fixture_path: pathlib.Path = FIXTURE, files: str | None = None) -> dict:
    fixture, digest = load_fixture(fixture_path)
    folder = files or os.environ.get("POP_FILES")
    base = {"check": "50-population-districts", "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                        "application": fixture["application"], "operation": fixture["operation"]}}
    if not folder or not pathlib.Path(folder).exists():
        return {**base, "agrees": None, "notRun": "POP_FILES names no folder of the downloads, so nothing was read.",
                "differs": [], "notEstablished": []}
    folder = pathlib.Path(folder)
    declared, theirs = fixture["declaredParameters"]["countries"], fixture["output"]["countries"]
    differs: list = []
    checked = {"districts": 0, "totals": 0, "shares": 0}
    largest = {"relativeTotal": 0.0, "share": 0.0}
    for code, spec in declared.items():
        gj = json.loads(verified(folder, spec["boundaries"]).read_text(encoding="utf-8"))
        districts = [{"name": f["properties"][spec["boundaries"]["nameField"]], "geometry": f["geometry"]}
                     for f in gj["features"]]
        mine = {name: {} for name in (d["name"] for d in districts)}
        for source in SOURCES:
            for name, t in totals_over(verified(folder, spec["rasters"][source]), districts).items():
                mine[name][source] = t
        with open(EXAMPLE / "data" / CENSUS[code], newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mine[row["name"]]["census"] = float(row["population"])
        sums = {s: sum(m[s]["total"] for m in mine.values()) for s in SOURCES}
        sums["census"] = sum(m["census"] for m in mine.values())
        for d in theirs[code]["districts"]:
            here = mine[d["name"]]
            checked["districts"] += 1
            for source in SOURCES:
                a, b = d[source], here[source]
                checked["totals"] += 1
                if a["cells"] != b["cells"]:
                    differs.append({"country": code, "district": d["name"], "source": source, "what": "cells",
                                    "fieldwork": a["cells"], "rasterio": b["cells"]})
                rel = abs(a["total"] - b["total"]) / max(abs(b["total"]), 1.0)
                largest["relativeTotal"] = max(largest["relativeTotal"], rel)
                if rel > 1e-9:
                    differs.append({"country": code, "district": d["name"], "source": source, "what": "total",
                                    "fieldwork": a["total"], "rasterio": b["total"], "relative": rel})
            for source in ["census", *SOURCES]:
                share = (here["census"] if source == "census" else here[source]["total"]) / sums[source]
                gap = abs(d["shares"][source] - share)
                checked["shares"] += 1
                largest["share"] = max(largest["share"], gap)
                if gap > 1e-12:
                    differs.append({"country": code, "district": d["name"], "source": source, "what": "share",
                                    "fieldwork": d["shares"][source], "rasterio": share})
    return {
        **base,
        "files": {code: {"boundaries": spec["boundaries"]["sha256"], **{s: spec["rasters"][s]["sha256"] for s in SOURCES}}
                  for code, spec in declared.items()},
        "agrees": not differs,
        "criteria": "Each district's cells with a value equal; each total within 1e-9 relative; each share within 1e-12",
        "checked": checked,
        "largest": largest,
        "differs": differs,
        "notEstablished": [
            "That any source is right: both sides total the same cells.",
            "That a district's cells are its people: a cell is counted whole by the rule of its centre, not by the share "
            "of it inside the district.",
            "That GHS-POP's window, cut from the global file with rasterio, is the window Fieldwork reads by range: a "
            "Fieldwork browser test reads it by range and gives the same shares to 0.1 %.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__,
                        "numpy": numpy.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"], report.get("notRun", ""))
    print("checked:", report.get("checked"), "largest:", report.get("largest"))
    for d in report["differs"][:30]:
        print(" ", d)
