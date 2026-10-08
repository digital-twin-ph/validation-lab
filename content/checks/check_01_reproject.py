"""Check 01: Fieldwork Reproject input against pyproj.

Recomputes the fixture's output from declaredParameters and input only, then
compares. Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/41-validation-lab.md
"""
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyproj

TOLERANCE_M = 1e-3  # Stated before running: agreement required below one millimetre.
ROOT = Path(__file__).resolve().parent.parent


def load_fixture(path: Path) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = (path.parent / (path.name + ".sha256")).read_text().split()[0]
    if digest != expected:
        raise SystemExit(f"Fixture hash mismatch: {digest} != {expected}")
    return json.loads(raw), digest


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    p = fixture["declaredParameters"]
    if p["datumShift"] != "none":
        raise SystemExit("This check covers projection changes on one datum only.")
    if p["targetCRS"] != "OGC:CRS84" or p["targetAxisOrder"] != "longitude-latitude":
        raise SystemExit(f"Unexpected target CRS contract: {p['targetCRS']} / {p['targetAxisOrder']}")

    # Build the transform from the declared definition, not from the source EPSG code,
    # so the comparison tests what Fieldwork says it did.
    transformer = pyproj.Transformer.from_crs(pyproj.CRS.from_proj4(p["definition"]),
                                              pyproj.CRS("OGC:CRS84"), always_xy=True)
    geod = pyproj.Geod(ellps="WGS84")
    output = {row["id"]: row for row in fixture["output"]}

    rows, worst = [], 0.0
    for item in fixture["input"]:
        lon, lat = transformer.transform(item["easting"], item["northing"])
        got = output[item["id"]]
        # Compare on the ground in metres, not in degrees: a degree is not a distance.
        _, _, separation_m = geod.inv(lon, lat, got["longitude"], got["latitude"])
        worst = max(worst, separation_m)
        rows.append({
            "id": item["id"],
            "reference": {"longitude": lon, "latitude": lat},
            "fieldwork": {"longitude": got["longitude"], "latitude": got["latitude"]},
            "separationM": separation_m,
        })

    return {
        "check": "01-reproject",
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
        },
        "toleranceM": TOLERANCE_M,
        "points": len(rows),
        "maxSeparationM": worst,
        "agrees": worst <= TOLERANCE_M,
        "rows": rows,
    }


if __name__ == "__main__":
    path = ROOT / "fixtures" / "reproject-utm35s-001.json"
    report = run(path)
    out = ROOT / "results" / "check-01-reproject.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    verdict = "AGREES" if report["agrees"] else "DISAGREES"
    print(f"{verdict}: {report['points']} points, maximum separation "
          f"{report['maxSeparationM']:.6g} m against a {report['toleranceM']} m tolerance")
    print(f"pyproj {report['environment']['pyproj']} / PROJ {report['environment']['proj']} "
          f"· {report['environment']['runtime']}")
    print(f"Wrote {out.relative_to(ROOT)}")
    sys.exit(0 if report["agrees"] else 1)
