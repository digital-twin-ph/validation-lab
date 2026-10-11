"""Check 14: Fieldwork Summarize points in polygons against shapely.

The John Snow example's actual question: how many deaths fall nearest each pump. Fieldwork
decides membership with its own point-in-polygon test; the reference uses GEOS predicates.

The boundary policy is the whole difficulty. Fieldwork's `include` means a location strictly
inside a polygon **or on its boundary**, which in GEOS terms is `covers`, not `contains`.
`exclude` is `contains`. Getting that mapping wrong would produce a check that passes on data
with no boundary cases and fails the moment one appears, so the mapping is declared here and
the number of boundary-lying locations is reported whether or not any exist.

Four comparisons, criteria fixed before running:

1. **The count per polygon**, exactly -- counts are integers and there is no tolerance.
2. **The numeric total per polygon**, summing the declared value field.
3. **The missing-value count per polygon**: a location whose field is absent or non-numeric
   contributes nothing and must be counted.
4. **The summary**: records, matched, unmatched, locations without coordinates, and
   locations belonging to more than one polygon.

That last number is the one that matters for reading the result. Every membership is
retained, so a location inside two polygons counts for both, and the per-polygon totals
therefore **must not be added** to a grand total. The check reports it so a reader can see
whether the warning applies to this data.

What this cannot establish: that the Voronoi assignment is a reasonable model of which pump
somebody drank from. It assumes people used the nearest pump by straight-line distance,
which is what the widget computes and not what anybody did.

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
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    policy = declared["boundary"]
    if policy not in ("include", "exclude"):
        raise SystemExit(f"Unknown boundary policy {policy!r}")
    # include = inside or on the edge = GEOS covers; exclude = strictly inside = contains.
    belongs = (lambda polygon, point: polygon.covers(point)) if policy == "include" \
        else (lambda polygon, point: polygon.contains(point))

    polygons = [(p["id"], shape(p["geometry"])) for p in fixture["input"]["polygons"]]
    counts = {identifier: 0 for identifier, _ in polygons}
    totals = {identifier: 0 for identifier, _ in polygons}
    missing_values = {identifier: 0 for identifier, _ in polygons}
    matched = unmatched = unlocated = multiple = on_boundary = 0

    for record in fixture["input"]["points"]:
        if not record["coordinates"]:
            unlocated += 1
            continue
        point = Point(record["coordinates"])
        hits = [identifier for identifier, polygon in polygons if belongs(polygon, point)]
        if any(polygon.boundary.distance(point) == 0 for _, polygon in polygons):
            on_boundary += 1
        if not hits:
            unmatched += 1
            continue
        matched += 1
        if len(hits) > 1:
            multiple += 1
        value = record["value"]
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        for identifier in hits:
            counts[identifier] += 1
            if declared["valueField"]:
                if numeric:
                    totals[identifier] += value
                else:
                    missing_values[identifier] += 1

    reported = {p["id"]: p for p in fixture["output"]["perPolygon"]}
    per_polygon, worst_total = [], 0.0
    for identifier, _ in polygons:
        row = reported.get(identifier, {})
        total_difference = abs((row.get("total") or 0) - totals[identifier])
        worst_total = max(worst_total, total_difference)
        per_polygon.append({
            "id": identifier,
            "countAgrees": row.get("count") == counts[identifier],
            "fieldworkCount": row.get("count"), "referenceCount": counts[identifier],
            "fieldworkTotal": row.get("total"), "referenceTotal": totals[identifier],
            "totalDifference": total_difference,
            "missingValuesAgree": (row.get("missingValues") or 0) == missing_values[identifier],
        })

    reported_summary = fixture["output"]["summary"]
    reference_summary = {"records": len(fixture["input"]["points"]), "matched": matched,
                         "unmatched": unmatched, "missingLocation": unlocated, "multiple": multiple,
                         "valueField": declared["valueField"]}
    summary_agrees = all(reported_summary.get(key) == value for key, value in reference_summary.items())

    counts_agree = all(row["countAgrees"] for row in per_polygon)
    missing_agree = all(row["missingValuesAgree"] for row in per_polygon)
    agrees = bool(counts_agree and missing_agree and summary_agrees and worst_total == 0)

    return {
        "check": "14-summarize-polygons",
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
            f"every per-polygon count, numeric total and missing-value count exact, and the summary of "
            f"records, matched, unmatched, unlocated and multiply-assigned locations exact, with boundary "
            f"policy {policy!r} read as GEOS "
            f"{'covers' if policy == 'include' else 'contains'}"
        ),
        "polygons": len(polygons),
        "points": len(fixture["input"]["points"]),
        "boundaryPolicy": policy,
        "locationsOnAPolygonEdge": on_boundary,
        "perPolygon": per_polygon,
        "reference": reference_summary,
        "fieldwork": reported_summary,
        "countsAgree": counts_agree,
        "missingValueCountsAgree": missing_agree,
        "summaryAgrees": summary_agrees,
        "worstTotalDifference": worst_total,
        "notEstablished": (
            "That nearest-pump assignment models which pump anybody drank from. It assumes the nearest pump "
            "by straight-line distance, which is what the widget computes and not what anybody did. And the "
            "per-polygon totals must not be added: every membership is retained, so an overlapping location "
            "counts more than once."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "summarize-polygons-soho-001.json")
    out = ROOT / "results" / "check-14-summarize-polygons.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 14: agrees={result['agrees']} over {result['points']} locations in "
          f"{result['polygons']} polygons -> {out.relative_to(ROOT.parent)}")
    print(f"  counts agree: {result['countsAgree']}, summary agrees: {result['summaryAgrees']}, "
          f"worst total difference {result['worstTotalDifference']}")
    print(f"  {result['fieldwork']['multiple']} location(s) in more than one polygon, "
          f"{result['locationsOnAPolygonEdge']} on an edge")
