"""Check 25: Fieldwork's rule over a quantity derived from geometry, against Shapely.

Three steps in one chain, each rebuilt from the declaration rather than taken on trust:
the convex hull of 250 located deaths, the area of that hull in a projected CRS, and the
classification of that area against a stated threshold.

**Why the chain and not the rule alone.** The rule itself is a comparison, and checking a
comparison proves nothing. What experiment 113 doubted is whether a quantity DERIVED from
geometry can reach a rule at all: until 2026-10-14 Fieldwork computed the hull's area,
published it in a receipt, and dropped it before anything downstream could read it. So the
check rebuilds the derivation too, and a disagreement in the status is as likely to be a
disagreement about the area as about the threshold.

**The status is on the polygon.** From `extent-review` 1.1.0 the ruleset hands back the
shapes it judged, each carrying `status` and `explanation`, instead of a table of
judgements with the geometry dropped. That is what this check compares: a classification
attached to a ring, against a classification this file computes for the ring it built
itself.

Criteria fixed before running, with reasons:

1. **The ring, vertex for vertex.** A convex hull is exact -- no tolerance, no
   approximation -- so any difference is a real difference. Compared after projecting
   Fieldwork's ring back, within 1e-6 degrees, which is about 0.1 mm.
2. **The area within 0.01%.** Both compute a shoelace area over projected metres, so they
   should agree to floating point; the tolerance is for the projection library, not the
   arithmetic.
3. **The status exactly, and for the stated reason.** Unknown when no area is attached,
   Review above the threshold, NoFlag at or below it. A status that agreed by accident --
   the right word from the wrong comparison -- would pass criterion 3 and fail this one, so
   the explanation is checked to carry the same numbers.

What this cannot establish: that 250,000 m2 is the right threshold, or that a convex hull
is the right outline. Both are the practitioner's to choose and neither Fieldwork nor this
check ships a basis for either. Nor does it establish that the rule fired in the reasoner:
the fixture records what EYE concluded, and this file recomputes the same comparison in
Python. Checking the reasoner against itself is check 23's job.

Independent by construction: nothing here imports Fieldwork code, and the chain is rebuilt
from `declaredParameters`.
Design record: fieldwork/docs/experiments/113-rules-over-geometry.md
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import numpy as np
import pyproj
import shapely
from shapely.geometry import MultiPoint, Polygon

RING_TOLERANCE = 1e-6          # degrees, about 0.1 mm
AREA_TOLERANCE = 0.0001        # 0.01% of area
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    threshold = declared["thresholdSquareMetres"]

    to_metric = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)
    located = [p["coordinates"] for p in fixture["input"]["points"] if p["coordinates"]]
    projected = [to_metric.transform(x, y) for x, y in located]

    # The derivation, rebuilt: hull, then its area in projected metres.
    hull = MultiPoint(projected).convex_hull
    area = hull.area
    reported_ring = [to_metric.transform(x, y) for x, y in fixture["output"]["ring"]]
    reported = Polygon(reported_ring)

    # Rings are compared as sets of corners, since either may start anywhere and either
    # winding is the same shape.
    mine = {(round(x, 6), round(y, 6)) for x, y in hull.exterior.coords}
    theirs = {(round(x, 6), round(y, 6)) for x, y in reported.exterior.coords}
    rings_agree = mine == theirs

    area_difference = abs(area - fixture["output"]["areaSquareMetres"]) / area
    expected_status = "Review" if area > threshold else "NoFlag"
    status = fixture["output"]["status"]
    status_agrees = status == expected_status
    # The right word for the right reason: the explanation must carry the same two numbers.
    explanation = fixture["output"]["explanation"] or ""
    reason_agrees = (f"{area / 1e6:.3f}" in explanation
                     and f"{threshold / 1e6:.3f}" in explanation
                     and ("≤" in explanation if status == "NoFlag" else ">" in explanation))

    agrees = bool(rings_agree and area_difference <= AREA_TOLERANCE
                  and status_agrees and reason_agrees)
    return {
        "check": "25-extent",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
            "pyproj": pyproj.__version__,
            "numpy": np.__version__,
        },
        "fixture": {
            "id": fixture["fixtureId"], "sha256": digest,
            "application": fixture["application"], "operation": fixture["operation"],
            "declaredMethod": declared["method"],
            "ruleset": declared["ruleset"],
        },
        "criterion": (
            f"hull ring vertex for vertex within {RING_TOLERANCE:g} degrees, area within "
            f"{AREA_TOLERANCE:.2%}, and the same status for the same stated comparison"
        ),
        "points": len(located),
        "thresholdSquareMetres": threshold,
        "reference": {
            "implementation": "shapely MultiPoint.convex_hull + .area in EPSG:32630",
            "hullVertices": len(mine), "areaSquareMetres": area, "status": expected_status,
        },
        "fieldwork": {
            "hullVertices": len(theirs),
            "areaSquareMetres": fixture["output"]["areaSquareMetres"],
            "status": status, "explanation": explanation,
            "statusCounts": fixture["output"]["statusCounts"],
        },
        "ringsAgree": rings_agree,
        "areaDifferenceFraction": area_difference,
        "statusAgrees": status_agrees,
        "reasonAgrees": reason_agrees,
        "notEstablished": (
            "That 250,000 m2 is the right threshold, or that a convex hull is the right outline: "
            "both are the practitioner's to choose and neither Fieldwork nor this check ships a "
            "basis for either. Nor that the rule fired in the reasoner -- the fixture records what "
            "EYE concluded and this file recomputes the same comparison in Python, which is a "
            "check of the derivation and the threshold, not of the inference. A hull is also an "
            "outline of what was OBSERVED: it encloses ground where nothing was recorded, and "
            "says nothing about what lies outside it."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "extent-soho-001.json")
    out = ROOT / "results" / "check-25-extent.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 25: agrees={result['agrees']} -> {out.relative_to(ROOT.parent)}")
    print(f"  hull {result['reference']['hullVertices']} vs {result['fieldwork']['hullVertices']} vertices, "
          f"rings agree={result['ringsAgree']}")
    print(f"  area {result['reference']['areaSquareMetres']:.1f} vs "
          f"{result['fieldwork']['areaSquareMetres']:.1f} m2 "
          f"({result['areaDifferenceFraction']*100:.4f}%)")
    print(f"  status {result['reference']['status']} vs {result['fieldwork']['status']}: "
          f"{result['fieldwork']['explanation']}")
