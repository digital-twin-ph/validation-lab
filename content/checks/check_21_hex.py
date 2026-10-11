"""Check 21: Fieldwork Group points in H3 cells against h3-py.

Fieldwork indexes with `h3-js`; the reference indexes with `h3-py`. Those are two bindings of
the same H3 library, so the **indexing** is not independently verified here and this check does
not pretend otherwise -- what it verifies is that Fieldwork calls it correctly, orders the
result as it says, and applies its own sparse-cell rule.

That rule is Fieldwork's alone and is the part worth checking. A cell holding fewer than
`minOccupancy` points is **omitted entirely**, not returned with a small count, so its points
disappear from the output. The widget's note says occupancy is not an anonymity guarantee; what
it does guarantee is that no cell in the output holds fewer than the minimum, and the price is
that some points are not represented at all.

Two cases, because the example's own setting does not exercise the rule it depends on. At
resolution 9 all 250 deaths fall into five cells, all above the minimum, so nothing is dropped.
Resolution 11 produces single-point cells, which is the case that makes points vanish.

Five comparisons per case, criteria fixed before running:

1. **The set of cells kept**, exactly.
2. **The count in each**, exactly.
3. **The boundary and centre** of each kept cell, against h3-py's own, to 1e-9 degrees.
4. **The order**, which the widget declares as the H3 index as a string.
5. **The accounting**: how many points were matched and how many the sparse rule dropped.

What this cannot establish: that H3 indexing is right -- both sides call the same C library --
or that aggregating to cells protects anybody. The second is the claim a reader will care
about and no check can settle it.

Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import h3

COORDINATE_TOLERANCE_DEG = 1e-9
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    minimum = declared["minOccupancy"]
    points = [p for p in fixture["input"]["points"] if p["coordinates"]]

    cases = []
    for case in fixture["output"]["cases"]:
        resolution = case["options"]["resolution"]
        counts = {}
        for point in points:
            longitude, latitude = point["coordinates"]
            cell = h3.latlng_to_cell(latitude, longitude, resolution)
            counts[cell] = counts.get(cell, 0) + 1
        kept = {cell: count for cell, count in counts.items() if count >= minimum}
        dropped_cells = len(counts) - len(kept)
        dropped_points = sum(count for count in counts.values() if count < minimum)

        reported = {c["h3"]: c for c in case["cells"]}
        same_cells = set(reported) == set(kept)
        counts_agree = all(reported[cell]["count"] == kept[cell] for cell in set(reported) & set(kept))
        ordered = [c["h3"] for c in case["cells"]] == sorted(kept)

        worst_boundary = worst_centre = 0.0
        for cell in sorted(set(reported) & set(kept)):
            # h3-py returns (lat, lng); the fixture carries (lng, lat) GeoJSON order.
            reference_boundary = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
            reported_boundary = [tuple(c) for c in reported[cell]["boundary"]]
            # Fieldwork closes the ring; h3 does not.
            if len(reported_boundary) == len(reference_boundary) + 1:
                reported_boundary = reported_boundary[:-1]
            if len(reported_boundary) != len(reference_boundary):
                worst_boundary = float("inf")
            else:
                for (ax, ay), (bx, by) in zip(reported_boundary, reference_boundary):
                    worst_boundary = max(worst_boundary, abs(ax - bx), abs(ay - by))
            latitude, longitude = h3.cell_to_latlng(cell)
            worst_centre = max(worst_centre,
                               abs(reported[cell]["centre"][0] - longitude),
                               abs(reported[cell]["centre"][1] - latitude))

        summary = case["summary"]
        accounting_agrees = (summary["records"] == len(fixture["input"]["points"])
                            and summary["matched"] == sum(kept.values())
                            and summary["unmatched"] == dropped_points)

        cases.append({
            "resolution": resolution,
            "cellsKeptFieldwork": len(reported),
            "cellsKeptReference": len(kept),
            "sameCells": same_cells,
            "countsAgree": counts_agree,
            "orderedByIndex": ordered,
            "worstBoundaryDifferenceDegrees": worst_boundary,
            "worstCentreDifferenceDegrees": worst_centre,
            "cellsDroppedBySparseRule": dropped_cells,
            "pointsDroppedBySparseRule": dropped_points,
            "accountingAgrees": accounting_agrees,
            "agrees": bool(same_cells and counts_agree and ordered and accounting_agrees
                           and max(worst_boundary, worst_centre) <= COORDINATE_TOLERANCE_DEG),
        })

    return {
        "check": "21-hex",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "h3": h3.__version__,
            "note": "h3-py and Fieldwork's h3-js are two bindings of the same C library, so the indexing is not independently verified.",
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredSparseRule": declared["sparseRule"],
        },
        "criterion": (
            f"per resolution: the same cells kept, the same count in each, each boundary and centre within "
            f"{COORDINATE_TOLERANCE_DEG:g} degrees of h3-py's, the cells ordered by H3 index, and the matched "
            f"and dropped point counts exact"
        ),
        "points": len(points),
        "minOccupancy": minimum,
        "cases": cases,
        "notEstablished": (
            "That H3 indexing is correct: both sides call the same C library through different bindings, so "
            "agreement is expected and says nothing about the index itself. And that aggregating to cells "
            "protects anybody -- occupancy is not an anonymity guarantee, and at resolution 11 the rule "
            "silently removes 13 of 250 deaths from the output rather than disclosing them."
        ),
        "agrees": all(case["agrees"] for case in cases),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "hex-soho-001.json")
    out = ROOT / "results" / "check-21-hex.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 21: agrees={result['agrees']} over {result['points']} points "
          f"-> {out.relative_to(ROOT.parent)}")
    for case in result["cases"]:
        print(f"  resolution {case['resolution']:>2}: {case['cellsKeptReference']:>3} cells kept, "
              f"{case['cellsDroppedBySparseRule']:>2} dropped, "
              f"{case['pointsDroppedBySparseRule']:>2} points removed, "
              f"worst coordinate difference "
              f"{max(case['worstBoundaryDifferenceDegrees'], case['worstCentreDifferenceDegrees']):.1e} deg")
