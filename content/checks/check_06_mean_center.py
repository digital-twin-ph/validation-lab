"""Check 06: Fieldwork Mean center against pyproj.

Two comparisons, both with criteria fixed before running:

1. The projected mean in metres, recomputed by transforming the input points to the
   declared CRS with pyproj and averaging without weights.
2. The returned CRS84 position, compared as a ground separation rather than a coordinate
   difference, because degrees are not a distance.

What this cannot establish: that an unweighted mean centre is a sensible summary of these
points. The fixture deliberately includes an outlier that pulls it.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/57-parity-evidence.md
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyproj

PROJECTED_TOLERANCE_M = 1e-3   # Same projection, same arithmetic: agreement well below a millimetre.
SEPARATION_TOLERANCE_M = 1e-3
ROOT = Path(__file__).resolve().parent.parent


def load_fixture(path: Path):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = (path.parent / (path.name + ".sha256")).read_text().split()[0]
    if digest != expected:
        raise SystemExit(f"Fixture hash mismatch: {digest} != {expected}")
    return json.loads(raw), digest


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["sourceCRS"] != "OGC:CRS84":
        raise SystemExit(f"Unexpected source CRS {declared['sourceCRS']}")

    forward = pyproj.Transformer.from_crs("OGC:CRS84", declared["computationCRS"], always_xy=True)
    inverse = pyproj.Transformer.from_crs(declared["computationCRS"], "OGC:CRS84", always_xy=True)
    geod = pyproj.Geod(ellps="WGS84")

    points = fixture["input"]["points"]
    eastings, northings = [], []
    for point in points:
        easting, northing = forward.transform(point["longitude"], point["latitude"])
        eastings.append(easting)
        northings.append(northing)
    reference_projected = [sum(eastings) / len(eastings), sum(northings) / len(northings)]
    reference_lon, reference_lat = inverse.transform(*reference_projected)

    reported = fixture["output"]
    easting_difference = abs(reported["projected"][0] - reference_projected[0])
    northing_difference = abs(reported["projected"][1] - reference_projected[1])
    _azimuth, _back, separation = geod.inv(
        reference_lon, reference_lat, reported["coordinates"][0], reported["coordinates"][1]
    )

    count_agrees = reported["count"] == len(points)
    agrees = (
        max(easting_difference, northing_difference) <= PROJECTED_TOLERANCE_M
        and separation <= SEPARATION_TOLERANCE_M
        and count_agrees
    )

    return {
        "check": "06-mean-center",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pyproj": pyproj.__version__,
            "proj": pyproj.proj_version_str,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredMethod": declared["method"],
        },
        "criterion": (
            f"projected mean within {PROJECTED_TOLERANCE_M:g} m on both axes, "
            f"returned position within {SEPARATION_TOLERANCE_M:g} m ground separation, and the input count unchanged"
        ),
        "points": len(points),
        "reference": {"projected": reference_projected, "coordinates": [reference_lon, reference_lat]},
        "fieldwork": {"projected": reported["projected"], "coordinates": reported["coordinates"]},
        "eastingDifferenceM": easting_difference,
        "northingDifferenceM": northing_difference,
        "separationM": separation,
        "countAgrees": count_agrees,
        "notEstablished": "Whether an unweighted mean centre is an appropriate summary. The fixture includes an outlier that pulls it, and both implementations are pulled identically.",
        "agrees": bool(agrees),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "mean-center-001.json")
    out = ROOT / "results" / "check-06-mean-center.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 06: agrees={result['agrees']} over {result['points']} points -> {out.relative_to(ROOT.parent)}")
    print(f"  easting {result['eastingDifferenceM']:.3e} m, northing {result['northingDifferenceM']:.3e} m, "
          f"separation {result['separationM']:.3e} m")
