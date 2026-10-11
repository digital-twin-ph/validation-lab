"""Check 08: Fieldwork Reachable corridor against Shapely.

The corridor is rebuilt from the declared rule with GEOS through Shapely: for each
directed edge leaving a reached junction, take the first `remainingM / lengthM` of its
length from that junction, buffer the collected lines by `bufferM`, and union them.

Criteria fixed before running, with reasons:

1. **Entered and partial segment counts, exactly.** Both implementations select edges by
   the same stated arithmetic over the same numbers, so a difference here is a difference
   in the rule rather than in the geometry engine.
2. **Area within 1%.** Not tighter, deliberately. Fieldwork buffers through Turf/JSTS in a
   local azimuthal equidistant projection; this buffers through GEOS in UTM zone 30N. Two
   projections and two engines at 8 segments per quadrant will not agree to the micrometre,
   and a criterion that pretended otherwise would be measuring the difference between
   map projections and calling it a defect.
3. **Symmetric difference at most 2% of the Fieldwork area.** Equal areas can still be
   different shapes, so the overlap is checked and not just the total.

What this cannot establish: that a 25 m half-width is right, or that the streets exist.
Both implementations trust the same edge geometry and the same lengths.

Independent by construction: nothing here imports Fieldwork code, and the corridor is
rebuilt from `declaredParameters` rather than compared feature by feature.
Design record: fieldwork/docs/experiments/84-reachable-corridor.md
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

AREA_TOLERANCE = 0.01          # 1% of area
SYMMETRIC_TOLERANCE = 0.02     # 2% of the Fieldwork area
ROOT = Path(__file__).resolve().parent.parent




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
    entered, partial_count, lines = 0, 0, []
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
        lines.append(piece)
        entered += 1

    reference = unary_union(MultiLineString(lines).buffer(
        declared["bufferM"], quad_segs=declared["quadrantSegments"]))
    reported = project(shape(fixture["output"]["corridor"]))

    counts_agree = (entered == fixture["output"]["enteredSegmentCount"]
                    and partial_count == fixture["output"]["partialSegmentCount"])
    area_difference = abs(reference.area - reported.area) / reported.area
    symmetric = reference.symmetric_difference(reported).area / reported.area
    agrees = (counts_agree
              and area_difference <= AREA_TOLERANCE
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
            f"entered and partial segment counts exactly, area within {AREA_TOLERANCE:.0%}, "
            f"and symmetric difference at most {SYMMETRIC_TOLERANCE:.0%} of the reported area"
        ),
        "reachedJunctions": len(remaining),
        "reference": {
            "implementation": "shapely.ops.substring + buffer + unary_union in EPSG:32630",
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
            "Whether a 25 m half-width is right, or whether the streets exist and are passable. "
            "Both implementations trust the same edge geometry and the same lengths, so a wrong "
            "network is wrong in both and this check still passes. The buffers are also taken in "
            "different projections -- Turf/JSTS local azimuthal equidistant against GEOS in UTM "
            "zone 30N -- which is why the area criterion is 1% rather than tighter."
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
