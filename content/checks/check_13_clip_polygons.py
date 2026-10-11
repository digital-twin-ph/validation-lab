"""Check 13: Fieldwork Clip polygons against shapely.

Fieldwork intersects with polyclip-ts; the reference intersects with GEOS. Both work on
longitude and latitude directly, because that is what the widget declares -- it does not
project first, and for a 1.4 km rectangle at 51.5 degrees north the difference is not
visible. The check compares what the widget claims, not what it might have claimed.

Three comparisons, criteria fixed before running:

1. **Each clipped polygon**, by symmetric difference against shapely's intersection of the
   same input polygon with the same boundary, matched by the polygon's own id.
2. **The count that survived.** A polygon whose intersection is empty is omitted rather than
   returned empty, so a disagreement about emptiness shows up as a count difference.
3. **That nothing escaped the boundary**: every output polygon within the boundary.

The fixture is the John Snow example's own chain -- nearest-pump Voronoi cells clipped to the
reporting rectangle. The cells are computed in a finite envelope and extend past the
rectangle, so the clip is doing real work: an unclipped cell claims ground the report does
not cover.

What this cannot establish: that clipping to a reporting rectangle is the right thing to do.
A clipped catchment is the part of that catchment the report covers, which is a different
object from the catchment, and both implementations produce it identically.

Tolerances are in square degrees, because the operation is. At this latitude 1e-13 square
degrees is under a square millimetre on the ground.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import shapely
from shapely.geometry import shape

AREA_TOLERANCE_DEG2 = 1e-13
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["computationCRS"] != "OGC:CRS84":
        raise SystemExit(f"Unexpected computation CRS {declared['computationCRS']}")

    boundary = shape(fixture["input"]["boundary"])
    reported = {p["id"]: shape(p["geometry"]) for p in fixture["output"]["polygons"]}

    reference, differences = {}, []
    for polygon in fixture["input"]["polygons"]:
        clipped = shape(polygon["geometry"]).intersection(boundary)
        if clipped.is_empty:
            continue
        reference[polygon["id"]] = clipped

    missing = sorted(set(reference) - set(reported))
    extra = sorted(set(reported) - set(reference))
    for identifier in sorted(set(reference) & set(reported)):
        difference = reported[identifier].symmetric_difference(reference[identifier]).area
        differences.append({"id": identifier, "symmetricDifferenceSquareDegrees": difference})

    worst = max((d["symmetricDifferenceSquareDegrees"] for d in differences), default=float("inf"))
    escaped = [identifier for identifier, polygon in reported.items()
               if polygon.difference(boundary).area > AREA_TOLERANCE_DEG2]
    counts_agree = (fixture["output"]["polygonCountOut"] == len(reference)
                    and len(reported) == len(reference))

    agrees = bool(not missing and not extra and not escaped
                  and worst <= AREA_TOLERANCE_DEG2 and counts_agree)

    return {
        "check": "13-clip-polygons",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredRule": declared["rule"],
        },
        "criterion": (
            f"the same polygons surviving the clip, each within {AREA_TOLERANCE_DEG2:g} square degrees of "
            f"shapely's intersection by symmetric difference, and no output polygon extending beyond the boundary"
        ),
        "polygonsIn": len(fixture["input"]["polygons"]),
        "polygonsOut": len(reported),
        "referenceOut": len(reference),
        "worstSymmetricDifferenceSquareDegrees": worst,
        "perPolygon": differences,
        "missingFromOutput": missing,
        "notInReference": extra,
        "escapedTheBoundary": escaped,
        "countsAgree": counts_agree,
        "notEstablished": (
            "That clipping to a reporting rectangle is the right thing to do. A clipped catchment is the part "
            "of that catchment the report covers, which is a different object from the catchment."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "clip-polygons-soho-001.json")
    out = ROOT / "results" / "check-13-clip-polygons.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 13: agrees={result['agrees']} over {result['polygonsIn']} polygons "
          f"-> {out.relative_to(ROOT.parent)}")
    print(f"  {result['polygonsOut']} survived against {result['referenceOut']}, worst symmetric difference "
          f"{result['worstSymmetricDifferenceSquareDegrees']:.3e} square degrees")
