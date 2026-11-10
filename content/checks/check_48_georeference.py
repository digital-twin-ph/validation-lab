"""Check 48: Fieldwork's placement of a map image from matched points, against GDAL's fit from ground control points.

Fieldwork experiment 201: Georeferenced map image can be placed by points matched between the image and today's map,
fitted affine by least squares. The fixture is that fit run through Fieldwork's own code, on South London's four
recorded control points (Snow's Map 2) and on a turned set with one pair 60 m off on purpose.

**Independent.** Here the same points go to GDAL's own fit from ground control points, `GDALGCPsToGeoTransform`,
through rasterio's `from_gcps`. GDAL's convention is the same continuous pixel position, (0, 0) at the image's top-left
corner. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **The same six numbers**, to 1e-10 degree a pixel and 1e-7 degree at the origin.
2. **The same residuals**, recomputed here from GDAL's transform, to 0.01 m.

What this cannot establish: that the points are the right features, or that a plan is accurate. Both sides fit the same
pairs; the residuals measure how well they agree with one placement, not whether the surveyor drew the place right.

Design record: fieldwork/docs/experiments/201-georeferencing-by-matching-points.md
"""
from __future__ import annotations

import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import rasterio
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "georef-001.json"
RESULT = HERE.parent / "results" / "check-48-georeference.json"


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    sets, differs = [], []
    for given, theirs in zip(fixture["input"]["sets"], fixture["output"]["sets"]):
        gcps = [GroundControlPoint(row=p["pixel"][1], col=p["pixel"][0], x=p["lonlat"][0], y=p["lonlat"][1], id=p["id"])
                for p in given["points"]]
        t = from_gcps(gcps)
        mine = {"a": t.a, "b": t.b, "c": t.c, "d": t.d, "e": t.e, "f": t.f}
        coefficient_gap = {k: abs(mine[k] - theirs["coefficients"][k]) for k in mine}
        residuals = []
        for p in given["points"]:
            x, y = p["pixel"]
            lon, lat = t * (x, y)
            east = (lon - p["lonlat"][0]) * 111_320 * math.cos(math.radians(p["lonlat"][1]))
            north = (lat - p["lonlat"][1]) * 110_570
            residuals.append({"id": p["id"], "eastM": east, "northM": north, "metres": math.hypot(east, north)})
        residual_gap = max(abs(r["metres"] - o["metres"]) for r, o in zip(residuals, theirs["residuals"]))
        ok_scale = all(coefficient_gap[k] <= 1e-10 for k in "abde")
        ok_origin = all(coefficient_gap[k] <= 1e-7 for k in "cf")
        ok_residuals = residual_gap <= 0.01
        sets.append({"name": given["name"], "points": len(gcps), "gdal": mine, "coefficientGap": coefficient_gap,
                     "residualGapM": residual_gap, "residualsM": [round(r["metres"], 2) for r in residuals],
                     "agrees": ok_scale and ok_origin and ok_residuals})
        if not (ok_scale and ok_origin and ok_residuals):
            differs.append({"set": given["name"], "scale": ok_scale, "origin": ok_origin, "residuals": ok_residuals})
    return {
        "check": "48-georeference",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": not differs,
        "criteria": "The same six affine numbers as GDAL's fit from the same ground control points (1e-10 degree a pixel, "
                    "1e-7 degree at the origin), and the same residuals to 0.01 m",
        "sets": sets,
        "differs": differs,
        "notEstablished": [
            "That the points are the right features: both sides fit the same pairs.",
            "That a plan is accurate: the residuals measure agreement with one placement, not the survey.",
            "The north-up model: GDAL's fit is affine; Fieldwork's north-up fit is checked against the hand fit in its unit tests.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
