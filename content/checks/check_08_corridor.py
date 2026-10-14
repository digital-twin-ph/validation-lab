"""Check 08: Fieldwork Reachable corridor against Shapely.

Rewritten 2026-10-14. Fieldwork stopped drawing the corridor as a constant strip: the walk
off the street at the end of a route is now charged, so the buffer at any point is
`min(bufferM, the budget left there)` and the corridor tapers to nothing where the time
runs out. The route also begins at the site rather than at the junction it was snapped to.
The previous version of this check rebuilt a constant-width strip and agreed with a
Fieldwork that drew one; both have changed, and the fixture with them.

The corridor is rebuilt from the declared rule with GEOS through Shapely: walk the first
`remainingM / lengthM` of each directed edge leaving a reached junction, plus the straight
first leg from the site, and buffer every metre of that route by what the budget allows
there.

**This reference is deliberately finer than Fieldwork.** It steps the route in 1 m pieces
and uses the exact remaining budget at each, where Fieldwork cuts at 12.5 m and rounds the
radius down into six steps. So the reference is the rule as stated and Fieldwork is a
conservative discretisation of it, which makes the comparison one-sided and says so.

Criteria fixed before running, with reasons:

1. **Entered and partial segment counts, exactly.** Both implementations select edges by
   the same stated arithmetic over the same numbers, so a difference here is a difference
   in the rule rather than in the geometry engine.
2. **Fieldwork's area at most 100.5% of the reference.** Its discretisation pulls both ways:
   rounding the radius down removes ground, while buffering each chunk separately gives the
   chunk's far end a round cap at the chunk's radius, where the rule gives a smaller one. The
   first is bounded by one step of bufferM/6 and the second by one cap per chunk, so neither
   can be large, and a Fieldwork corridor materially larger than the stated rule would mean
   the taper is not tracking the budget. The half per cent also absorbs the two engines and
   two projections, which is what the old 1% criterion was for.
3. **Fieldwork's area at least 85% of the reference.** A deficit beyond that would mean the
   taper is biting somewhere the rule does not put it.
4. **Symmetric difference at most 8% of the Fieldwork area.** Equal areas can still be
   different shapes. It is looser than the 2% the constant-width check used because the
   discretisations differ along the whole frontier by construction, not only in total.

What this cannot establish: that a 25 m final walk is right, that the ground beside a
street can be walked at all, or that the streets exist. Both implementations trust the
same edge geometry and the same lengths.

Independent by construction: nothing here imports Fieldwork code, and the corridor is
rebuilt from `declaredParameters` rather than compared feature by feature.
Design record: fieldwork/docs/experiments/114-the-three-segments-of-a-walk.md
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture, verified_asset

import numpy as np
import pyproj
import shapely
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import substring, unary_union

AREA_AT_MOST = 1.005           # Fieldwork may not exceed the stated rule by more than 0.5%
AREA_AT_LEAST = 0.85           # nor fall more than 15% short of it
SYMMETRIC_TOLERANCE = 0.08     # 8% of the Fieldwork area
STEP_M = 1.0                   # the reference walks the route in 1 m pieces
ROOT = Path(__file__).resolve().parent.parent


def tapered(line, remaining_m, final_leg_m, quad_segs):
    """Buffer a reached stretch by the walk its budget allows, a metre at a time.

    The rule as declared, at the finest step this check can afford: at distance d along the
    line the walk off the street is min(final_leg_m, remaining_m - d), and the corridor is
    the union of those discs. Fieldwork approximates the same shape with coarser pieces.
    """
    pieces = []
    walked = 0.0
    usable = min(line.length, remaining_m)
    while walked < usable:
        step = min(STEP_M, usable - walked)
        piece = substring(line, walked, walked + step)
        radius = min(final_leg_m, remaining_m - (walked + step))
        walked += step
        if radius <= 0 or piece.is_empty:
            continue
        pieces.append(piece.buffer(radius, quad_segs=quad_segs))
    return pieces




def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["direction"] != "outbound":
        raise SystemExit(f"This check covers outbound travel only, not {declared['direction']}")

    to_metric = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)
    def project(geom):
        return shapely.transform(
            geom, lambda coords: np.column_stack(to_metric.transform(coords[:, 0], coords[:, 1])))

    nodes = {n["id"]: n["coordinates"] for n in fixture["input"]["network"]["nodes"]}
    remaining = {r["networkNodeId"]: r["remainingM"] for r in fixture["input"]["reached"]}

    # Edges leaving each reached junction, oriented to start at that junction. A stated
    # geometry may be given either way round, so it is oriented by which end is nearer.
    entered, partial_count, pieces = 0, 0, []
    final_leg_m = declared["bufferM"]
    quad_segs = declared["quadrantSegments"]
    # The first leg: the straight walk from the site to the junction it entered at, charged
    # against the budget like any other metre. Absent from fixtures exported before
    # 2026-10-14, where the corridor began at the junction.
    origin = fixture["input"].get("origin")
    if origin:
        entry = project(shapely.Point(nodes[origin["networkNodeId"]]))
        site = project(shapely.Point(origin["coordinates"]))
        budget_at_site = remaining[origin["networkNodeId"]] + origin["snapDistanceM"]
        pieces += tapered(LineString([site, entry]), budget_at_site, final_leg_m, quad_segs)
    for edge in fixture["input"]["network"]["edges"]:
        left = remaining.get(edge["from"])
        if left is None or left <= 0:
            continue
        coords = edge.get("geometry") or [nodes[edge["from"]], nodes[edge["to"]]]
        line = project(LineString(coords))
        start = project(shapely.Point(nodes[edge["from"]]))
        if line.coords[0] != line.coords[-1]:
            head = shapely.Point(line.coords[0]).distance(start)
            tail = shapely.Point(line.coords[-1]).distance(start)
            if head > tail:
                line = LineString(list(line.coords)[::-1])
        fraction = min(1.0, left / edge["lengthM"])
        if fraction < 1:
            partial_count += 1
        piece = substring(line, 0.0, fraction, normalized=True)
        if piece.is_empty or piece.length <= 0:
            continue
        pieces += tapered(piece, left, final_leg_m, quad_segs)
        entered += 1

    reference = unary_union(pieces)
    reported = project(shape(fixture["output"]["corridor"]))

    counts_agree = (entered == fixture["output"]["enteredSegmentCount"]
                    and partial_count == fixture["output"]["partialSegmentCount"])
    # One-sided: the fraction of the stated rule's ground that Fieldwork draws. Above 1 it
    # claims ground the rule does not allow; below 1 it is the coarser discretisation.
    area_ratio = reported.area / reference.area
    area_difference = abs(reference.area - reported.area) / reported.area
    symmetric = reference.symmetric_difference(reported).area / reported.area
    agrees = (counts_agree
              and AREA_AT_LEAST <= area_ratio <= AREA_AT_MOST
              and symmetric <= SYMMETRIC_TOLERANCE)

    return {
        "check": "08-corridor",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
            "pyproj": pyproj.__version__,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredMethod": declared["method"],
        },
        "criterion": (
            f"entered and partial segment counts exactly, Fieldwork's area between "
            f"{AREA_AT_LEAST:.0%} and {AREA_AT_MOST:.1%} of the rule rebuilt at {STEP_M:.0f} m "
            f"steps, and symmetric difference at most {SYMMETRIC_TOLERANCE:.0%} of it"
        ),
        "reachedJunctions": len(remaining),
        "areaRatio": area_ratio,
        "firstLegIncluded": bool(origin),
        "reference": {
            "implementation": f"shapely.ops.substring + tapered buffer at {STEP_M:.0f} m steps + unary_union in EPSG:32630",
            "enteredSegments": entered, "partialSegments": partial_count,
            "areaSquareMetres": reference.area,
        },
        "fieldwork": {
            "enteredSegments": fixture["output"]["enteredSegmentCount"],
            "partialSegments": fixture["output"]["partialSegmentCount"],
            "areaSquareMetres": reported.area,
        },
        "countsAgree": counts_agree,
        "areaDifferenceFraction": area_difference,
        "symmetricDifferenceFraction": symmetric,
        "notEstablished": (
            "Whether a 25 m final walk off the street is right, whether the ground beside a "
            "street can be walked at all, or whether the streets exist and are passable. Both "
            "implementations trust the same edge geometry and the same lengths, so a wrong "
            "network is wrong in both and this check still passes. Nor does it establish that "
            "Fieldwork's discretisation is close enough for any particular use: it establishes "
            "that Fieldwork draws no more ground than the rule allows, and how much less."
        ),
        "agrees": bool(agrees),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "corridor-soho-001.json")
    out = ROOT / "results" / "check-08-corridor.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 08: agrees={result['agrees']} -> {out.relative_to(ROOT.parent)}")
    print(f"  segments entered {result['reference']['enteredSegments']} vs "
          f"{result['fieldwork']['enteredSegments']}, partial "
          f"{result['reference']['partialSegments']} vs {result['fieldwork']['partialSegments']}")
    print(f"  area {result['reference']['areaSquareMetres']:.0f} vs "
          f"{result['fieldwork']['areaSquareMetres']:.0f} m2 "
          f"({result['areaDifferenceFraction']*100:.3f}%), symmetric difference "
          f"{result['symmetricDifferenceFraction']*100:.3f}%")
