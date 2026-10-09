"""Check 05: Fieldwork Calculate area against independent spherical and geodesic areas.

Three different questions are kept apart, because collapsing them would turn a
methodological statement into a false failure:

1. Implementation. Does the widget compute the spherical formula it declares? Checked
   against an independent closed-form expression of the same quantity, where the polygon
   boundary follows parallels and meridians. Criterion stated before running.
2. Edge model. How far is that from a geodesic polygon area on the same sphere, whose
   edges are great circles? Reported, never failed: it is a modelling difference.
3. Earth model. How far is it from a WGS84 ellipsoidal geodesic area? Reported. This is
   the approximation the widget already declares when it says "spherical".

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/57-parity-evidence.md
"""
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyproj

RELATIVE_TOLERANCE = 1e-9  # Stated before running: same formula, so agreement should be near machine precision.
ROOT = Path(__file__).resolve().parent.parent


def load_fixture(path: Path):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = (path.parent / (path.name + ".sha256")).read_text().split()[0]
    if digest != expected:
        raise SystemExit(f"Fixture hash mismatch: {digest} != {expected}")
    return json.loads(raw), digest


def ring_area_parallels(ring, radius):
    """Area of a ring whose boundary follows parallels and meridians, on a sphere.

    Written as the sum (lon2 - lon1) * (2 + sin lat1 + sin lat2), which is a different
    expression from the running-triple form the widget's library uses, so agreement is
    evidence about the implementation rather than a transliteration of it.
    """
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        total += math.radians(lon2 - lon1) * (
            2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs(total) * radius * radius / 2.0


def polygon_area_parallels(geometry, radius):
    rings = geometry["coordinates"]
    outer = ring_area_parallels(rings[0], radius)
    holes = sum(ring_area_parallels(r, radius) for r in rings[1:])
    return outer - holes


def geodesic_area(geometry, geod):
    """Great-circle-edged polygon area, holes subtracted, using GeographicLib via pyproj."""
    rings = geometry["coordinates"]
    def one(ring):
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        area, _perimeter = geod.polygon_area_perimeter(lons, lats)
        return abs(area)
    return one(rings[0]) - sum(one(r) for r in rings[1:])


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["model"] != "sphere":
        raise SystemExit(f"This check covers the spherical model only, not {declared['model']}.")
    radius = declared["earthRadiusM"]
    sphere = pyproj.Geod(a=radius, f=0)
    wgs84 = pyproj.Geod(ellps="WGS84")

    geometries = {case["id"]: case["geometry"] for case in fixture["input"]["cases"]}
    cases, agrees = [], True
    for reported in fixture["output"]:
        geometry = geometries[reported["id"]]
        reference = polygon_area_parallels(geometry, radius)
        fieldwork = reported["squareMetres"]
        relative = abs(fieldwork - reference) / reference
        case_agrees = relative <= RELATIVE_TOLERANCE
        agrees &= case_agrees
        great_circle = geodesic_area(geometry, sphere)
        ellipsoidal = geodesic_area(geometry, wgs84)
        cases.append({
            "id": reported["id"],
            "fieldworkSquareMetres": fieldwork,
            "referenceSquareMetres": reference,
            "relativeDifference": relative,
            "agrees": case_agrees,
            "context": {
                "greatCircleEdgedSphereSquareMetres": great_circle,
                "relativeToGreatCircleEdges": (fieldwork - great_circle) / great_circle,
                "wgs84EllipsoidalSquareMetres": ellipsoidal,
                "relativeToEllipsoidal": (fieldwork - ellipsoidal) / ellipsoidal,
            },
        })

    return {
        "check": "05-area",
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
        "criterion": f"relative difference at most {RELATIVE_TOLERANCE:g} against an independent spherical area with parallel-and-meridian edges",
        "reported": {
            "edgeModel": "The widget's boundary follows parallels and meridians. A geodesic area uses great-circle edges; the difference is a modelling choice, not an error.",
            "earthModel": "The widget declares a sphere of the stated radius. The WGS84 comparison quantifies that declared approximation.",
        },
        "cases": cases,
        "agrees": bool(agrees),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "measure-area-001.json")
    out = ROOT / "results" / "check-05-area.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 05: agrees={result['agrees']} over {len(result['cases'])} cases -> {out.relative_to(ROOT.parent)}")
    for case in result["cases"]:
        c = case["context"]
        print(f"  {case['id']:<24} rel {case['relativeDifference']:.3e}"
              f"  vs great-circle edges {c['relativeToGreatCircleEdges']*100:+.4f}%"
              f"  vs WGS84 {c['relativeToEllipsoidal']*100:+.4f}%")
