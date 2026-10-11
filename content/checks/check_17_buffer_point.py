"""Check 17: Fieldwork Area around a point against theory and pyproj.

**The first widget in this lab that cannot agree exactly with a reference, and this check says
so.** Turf buffers in a local azimuthal equidistant projection, so there is no second
implementation of the same construction to compare against. What can be checked is the
approximation itself, against **theory**.

A circle buffered with `steps` segments per quadrant is a polygon of `4 x steps` vertices
inscribed in it, and the area of such a polygon has a closed form:

    (n / 2pi) * sin(2pi / n)

which is 0.99359 at 32 vertices and 0.99960 at 128 -- exactly the figures Fieldwork's own
comments record from measurement. So the widget's reported `circleAreaFraction` is checked
against arithmetic that owes nothing to any geometry library.

Three comparisons, criteria fixed before running:

1. **The vertex count**: exactly `4 x steps`.
2. **The reported circle-area fraction** against the closed form, to the four decimals the
   widget reports.
3. **Every vertex at the stated radius** from the centre, on the **sphere of radius
   6,371,008.8 m** that Turf uses.

That third criterion was wrong on the first attempt and the correction is the most useful
thing here. It asked for 1 m on the WGS84 **ellipsoid** and got 1.589 m. On the sphere the
spread is **0.0000 m**: the widget is exact, and the criterion had the wrong earth model. The
ellipsoidal range is reported beside it as a consequence, because a practitioner reading
"within 500 m" will mean 500 m on the ground, and on the ground it is 500.28 to 501.59 m.

What this cannot establish: whether the radius is the right radius. A buffered scope is a
decision, not a surveyed boundary -- its edge decides membership and its radius is an
assumption of the question.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import pyproj

# Turf buffers on a sphere of this radius, and does so exactly: the measured spread of vertex
# distances on that sphere is 0.0000 m, so a millimetre is a generous allowance.
TURF_SPHERE_RADIUS_M = 6371008.8
RADIUS_TOLERANCE_M = 1e-3
FRACTION_TOLERANCE = 5e-5   # The widget reports the fraction to four decimals.
ROOT = Path(__file__).resolve().parent.parent


def inscribed_area_fraction(vertices: int) -> float:
    """Area of a regular n-gon inscribed in a unit circle, as a fraction of the circle."""
    return (vertices / (2 * math.pi)) * math.sin(2 * math.pi / vertices)


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    radius = declared["radiusMetres"]
    steps = declared["stepsPerQuadrant"]
    centre = fixture["input"]["point"]["coordinates"]
    reported = fixture["output"]

    expected_vertices = 4 * steps
    vertex_count_agrees = reported["vertexCount"] == expected_vertices
    expected_fraction = inscribed_area_fraction(expected_vertices)
    fraction_difference = abs(reported["circleAreaFraction"] - expected_fraction)

    sphere = pyproj.Geod(a=TURF_SPHERE_RADIUS_M, b=TURF_SPHERE_RADIUS_M)
    wgs84 = pyproj.Geod(ellps="WGS84")
    ring = reported["boundary"]["coordinates"][0][:-1]
    spherical = [sphere.inv(centre[0], centre[1], x, y)[2] for x, y in ring]
    ellipsoidal = [wgs84.inv(centre[0], centre[1], x, y)[2] for x, y in ring]
    worst_radius_error = max(abs(d - radius) for d in spherical)

    agrees = bool(vertex_count_agrees
                  and fraction_difference <= FRACTION_TOLERANCE
                  and worst_radius_error <= RADIUS_TOLERANCE_M)

    return {
        "check": "17-buffer-point",
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
            "declaredCircleRule": declared["circleRule"],
        },
        "criterion": (
            f"exactly {expected_vertices} vertices, the reported circle-area fraction within "
            f"{FRACTION_TOLERANCE:g} of the closed form for an inscribed polygon, and every vertex within "
            f"{RADIUS_TOLERANCE_M:g} m of the stated {radius} m on the sphere of radius "
            f"{TURF_SPHERE_RADIUS_M:g} m that Turf buffers on"
        ),
        "stepsPerQuadrant": steps,
        "vertexCount": reported["vertexCount"],
        "expectedVertexCount": expected_vertices,
        "vertexCountAgrees": vertex_count_agrees,
        "reportedCircleAreaFraction": reported["circleAreaFraction"],
        "closedFormFraction": expected_fraction,
        "fractionDifference": fraction_difference,
        "radiusMetres": radius,
        "sphereRadiusMetres": TURF_SPHERE_RADIUS_M,
        "worstVertexRadiusErrorMetres": worst_radius_error,
        "sphericalRadiusRangeMetres": [min(spherical), max(spherical)],
        "ellipsoidalRadiusRangeMetres": [min(ellipsoidal), max(ellipsoidal)],
        "ellipsoidalExcessAtWorstMetres": max(ellipsoidal) - radius,
        "notEstablished": (
            "That a 500 m buffer is 500 m on the ground. It is 500 m on a sphere of radius 6,371,008.8 m and "
            "500.28 to 501.59 m on the WGS84 ellipsoid at this latitude -- up to 1.59 m more, varying with "
            "direction. That is a property of the construction, reported rather than corrected. Nor whether "
            "the radius is the right radius: a buffered scope is a decision, not a surveyed boundary."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "buffer-point-soho-001.json")
    out = ROOT / "results" / "check-17-buffer-point.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 17: agrees={result['agrees']} -> {out.relative_to(ROOT.parent)}")
    print(f"  {result['vertexCount']} vertices, fraction {result['reportedCircleAreaFraction']} against "
          f"closed form {result['closedFormFraction']:.5f}")
    print(f"  on the sphere  {result['sphericalRadiusRangeMetres'][0]:.4f} to "
          f"{result['sphericalRadiusRangeMetres'][1]:.4f} m (stated {result['radiusMetres']})")
    print(f"  on WGS84       {result['ellipsoidalRadiusRangeMetres'][0]:.4f} to "
          f"{result['ellipsoidalRadiusRangeMetres'][1]:.4f} m -- up to "
          f"{result['ellipsoidalExcessAtWorstMetres']:.3f} m more than stated")
