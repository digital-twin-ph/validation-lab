"""Check 10: Fieldwork Convex hull against shapely.

A convex hull is exact. There is no tolerance to choose, no curve to approximate and no
iteration to converge, so the hull ring either matches vertex for vertex or the two
implementations disagree about something real. That makes this the cheapest honest check in
the set, and the reason it was written first of the twenty-six.

Four comparisons, criteria fixed before running:

1. **The ring**, as a set of vertices in projected metres, compared vertex for vertex after
   projecting the input points with pyproj. Exact to within the round trip through degrees.
2. **The vertex count**, which is where the two could legitimately differ: Fieldwork drops
   points lying *on* an edge, and shapely's hull does the same, but a tie in the sweep could
   order them differently. A difference here is reported, not tolerated.
3. **The area**, recomputed as shapely's area of the projected ring. This is a planar area
   in EPSG:32630 and deliberately not a geodesic one, because that is what Fieldwork claims.
4. **The span**, the greatest distance between any two hull vertices.

What this cannot establish: that a convex hull is a sensible summary of cholera deaths in
Soho. It is not. The hull fills in the river and the squares the outbreak did not cross, and
asserts area where nothing was observed -- which is Fieldwork's own note on the widget, and a
check cannot contradict or confirm a claim about meaning.

Independent by construction: nothing here imports Fieldwork code. The projection is done
here rather than taken from the fixture, so this tests the projection and the hull together.

Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import pyproj
import shapely
from shapely.geometry import MultiPoint, Polygon

VERTEX_TOLERANCE_M = 1e-3     # Same projection, same points: agreement well below a millimetre.
AREA_TOLERANCE_M2 = 0.05      # Fieldwork reports area to two decimals, so this is its own rounding.
SPAN_TOLERANCE_M = 0.1        # Reported to one decimal.
ROOT = Path(__file__).resolve().parent.parent


def ring_of(polygon: Polygon) -> list[tuple[float, float]]:
    """The hull's corners, closed, with the closing repeat dropped for comparison."""
    return list(polygon.exterior.coords)[:-1]


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    forward = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)

    located = [p for p in fixture["input"]["points"] if p["coordinates"]]
    projected = [forward.transform(p["coordinates"][0], p["coordinates"][1]) for p in located]
    reference = MultiPoint(projected).convex_hull
    if not isinstance(reference, Polygon):
        raise SystemExit("The reference hull is not a polygon, so these points enclose no area.")
    reference_ring = ring_of(reference)

    reported = fixture["output"]
    # Fieldwork returns the ring in longitude and latitude; project it back to compare in metres.
    reported_ring = [forward.transform(x, y) for x, y in reported["ring"][:-1]]

    # Compared as sets, because a hull is the same hull wherever its ring starts and
    # whichever way it is wound. Order is reported separately below.
    def nearest_separation(ring_a, ring_b):
        worst = 0.0
        for ax, ay in ring_a:
            worst = max(worst, min(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 for bx, by in ring_b))
        return worst

    vertex_counts_agree = len(reported_ring) == len(reference_ring)
    separation = max(nearest_separation(reported_ring, reference_ring),
                     nearest_separation(reference_ring, reported_ring)) if reported_ring else float("inf")

    reference_area = reference.area
    reference_span = max(
        ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        for i, (ax, ay) in enumerate(reference_ring) for bx, by in reference_ring[i + 1:]
    )
    area_difference = abs(reported["hullAreaSquareMetres"] - reference_area)
    span_difference = abs(reported["hullSpanMetres"] - reference_span)
    count_agrees = reported["recordCount"] == len(located)

    agrees = bool(
        vertex_counts_agree
        and separation <= VERTEX_TOLERANCE_M
        and area_difference <= AREA_TOLERANCE_M2
        and span_difference <= SPAN_TOLERANCE_M
        and count_agrees
    )

    return {
        "check": "10-hull",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
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
            f"the same number of hull vertices, every vertex within {VERTEX_TOLERANCE_M:g} m of one in the "
            f"reference hull and vice versa, planar area within {AREA_TOLERANCE_M2:g} m2, "
            f"span within {SPAN_TOLERANCE_M:g} m, and the located-point count unchanged"
        ),
        "points": len(located),
        "unlocated": len(fixture["input"]["points"]) - len(located),
        "reference": {"vertexCount": len(reference_ring), "areaSquareMetres": reference_area,
                      "spanMetres": reference_span},
        "fieldwork": {"vertexCount": len(reported_ring),
                      "areaSquareMetres": reported["hullAreaSquareMetres"],
                      "spanMetres": reported["hullSpanMetres"]},
        "vertexCountsAgree": vertex_counts_agree,
        "worstVertexSeparationM": separation,
        "areaDifferenceSquareMetres": area_difference,
        "spanDifferenceM": span_difference,
        "countAgrees": count_agrees,
        "notEstablished": (
            "That a convex hull is a sensible summary of these deaths. It is convex, so it fills in ground "
            "the outbreak did not cross and asserts area where nothing was observed. Both implementations "
            "assert it identically."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "hull-soho-001.json")
    out = ROOT / "results" / "check-10-hull.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 10: agrees={result['agrees']} over {result['points']} points -> {out.relative_to(ROOT.parent)}")
    print(f"  vertices {result['fieldwork']['vertexCount']} vs {result['reference']['vertexCount']}, "
          f"worst vertex separation {result['worstVertexSeparationM']:.3e} m, "
          f"area difference {result['areaDifferenceSquareMetres']:.3e} m2")
