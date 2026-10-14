"""Check 24: Fieldwork Reproject points (forward projection) against pyproj.

The companion to check 01, which recomputes the INVERSE transform that `reproject`
performed until release 0.1.0. From 0.2.0 the widget projects forward, CRS84 to a UTM
zone, and that direction had no parity evidence: the catalog reported it as
"agrees - earlier release" because the only check covering the widget covers the
contract it no longer has.

A round trip through both directions is not a substitute. Fieldwork's forward and
inverse transforms come from the same proj4 build, so a fault in proj4's UTM would
round-trip perfectly and still be wrong. This recomputes from declaredParameters and
input only; nothing here imports Fieldwork code.

Design record: fieldwork/docs/experiments/111-splitting-reproject.md
"""
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import pyproj

# Stated before running. Fieldwork stores projected coordinates to three decimals, so the
# rounding alone can displace a point by up to half a millimetre on each axis -- hypot of
# two half-units is about 0.7 mm. One millimetre is the smallest tolerance that rounding
# does not already exhaust, and it is the same figure check 01 states for the inverse.
TOLERANCE_M = 1e-3
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    p = fixture["declaredParameters"]
    if p["datumShift"] != "none":
        raise SystemExit("This check covers projection changes on one datum only.")
    if p["sourceCRS"] != "OGC:CRS84" or p["axisOrder"] != "longitude-latitude":
        raise SystemExit(f"Unexpected source contract: {p['sourceCRS']} / {p['axisOrder']}")
    if p["targetAxisOrder"] != "easting-northing" or p.get("targetUnits") != "metre":
        raise SystemExit(f"Unexpected target contract: {p['targetAxisOrder']} / {p.get('targetUnits')}")

    # Built from the declared proj4 definition rather than from the EPSG code, so what is
    # compared is what Fieldwork says it did and not what its zone number implies.
    declared = pyproj.CRS.from_proj4(p["definition"])
    transformer = pyproj.Transformer.from_crs(pyproj.CRS("OGC:CRS84"), declared, always_xy=True)

    # The declared definition and the declared EPSG code must be the same frame. Fieldwork
    # builds the proj4 string and the "EPSG:326xx" label from the zone separately, so an
    # off-by-one in either would otherwise pass unnoticed: every coordinate would agree with
    # a definition that disagrees with the code the receipts carry.
    code_matches = pyproj.CRS(p["targetCRS"]).equals(declared, ignore_axis_order=True)

    output = {row["id"]: row for row in fixture["output"]}
    rows, worst = [], 0.0
    for item in fixture["input"]:
        easting, northing = transformer.transform(item["longitude"], item["latitude"])
        got = output[item["id"]]
        # Both sides are already metres in the same projected plane, so the separation is a
        # plane distance. It is not quite a ground distance -- near the zone edge the plane
        # stretches by about one part in 2,500 -- which at these magnitudes is a rounding
        # error on a rounding error, and is stated rather than silently ignored.
        separation_m = math.hypot(easting - got["easting"], northing - got["northing"])
        worst = max(worst, separation_m)
        rows.append({
            "id": item["id"],
            "input": {"longitude": item["longitude"], "latitude": item["latitude"]},
            "reference": {"easting": easting, "northing": northing},
            "fieldwork": {"easting": got["easting"], "northing": got["northing"]},
            "separationM": separation_m,
        })

    return {
        "check": "24-project-forward",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": "pyodide" in sys.modules or platform.system() == "Emscripten",
            "pyproj": pyproj.__version__,
            "proj": pyproj.proj_version_str,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "selfReportedMaxRoundTripM": fixture["selfReported"]["maxRoundTripM"],
            "coordinateDecimals": fixture["selfReported"]["coordinateDecimals"],
        },
        "toleranceM": TOLERANCE_M,
        "points": len(rows),
        "maxSeparationM": worst,
        "declaredCodeMatchesDefinition": code_matches,
        "agrees": worst <= TOLERANCE_M and code_matches,
        "rows": rows,
    }


if __name__ == "__main__":
    path = ROOT / "fixtures" / "project-forward-utm30n-001.json"
    report = run(path)
    out = ROOT / "results" / "check-24-project-forward.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    verdict = "AGREES" if report["agrees"] else "DISAGREES"
    print(f"{verdict}: {report['points']} points, maximum separation "
          f"{report['maxSeparationM']:.6g} m against a {report['toleranceM']} m tolerance")
    if not report["declaredCodeMatchesDefinition"]:
        print("The declared EPSG code and the declared proj4 definition are not the same frame.")
    print(f"pyproj {report['environment']['pyproj']} / PROJ {report['environment']['proj']} "
          f"· {report['environment']['runtime']}")
    print(f"Wrote {out.relative_to(ROOT)}")
    sys.exit(0 if report["agrees"] else 1)
