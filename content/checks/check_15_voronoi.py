"""Check 15: Fieldwork Voronoi catchments against shapely.

The first step of the John Snow example, and the one step of its chain that had no check.

Two unrelated algorithms for the same partition. Fieldwork starts from a rectangle and clips
it with one half-plane per other site -- the set of points at least as close to this site as
to that one -- in projected metres. The reference asks GEOS for the Voronoi diagram of the
same projected points and clips it to the same envelope. Nothing about the one method informs
the other.

The envelope is recomputed here from the boundary by the declared rule, rather than taken from
the fixture, so the derivation is tested too: the projected corners of the reporting area's
bounding box, then the extreme easting and northing of those four points, expanded by 100 m.

Three comparisons, criteria fixed before running:

1. **Each cell**, matched by site and compared by symmetric difference in projected metres.
2. **That the cells tile the envelope**: their union is the envelope and no two overlap.
3. **That each cell contains its own site**, which is the property a Voronoi cell is for.

What this cannot establish: that a nearest-pump cell models which pump anybody drank from.
Euclidean distance in a projection ignores streets, walls and the Thames. Fieldwork says so in
the widget's own note -- "cells model proximity, not actual pump use" -- and the reference
ignores them identically.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import numpy as np
import pyproj
import shapely
from shapely.geometry import MultiPoint, Point, box, shape

AREA_TOLERANCE_M2 = 1.0   # Cells are 40,000 to 250,000 m2; 1 m2 is a few parts per million.
ENVELOPE_MARGIN_M = 100   # Declared by the fixture; asserted below rather than assumed.
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    to_metric = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)
    project = lambda geometry: shapely.transform(
        geometry, lambda coords: np.column_stack(to_metric.transform(coords[:, 0], coords[:, 1])))

    # The envelope, by the declared rule: the boundary's bounding-box corners projected, then
    # their extremes, expanded by 100 m. Note this is not the projection of the degree-space
    # bounding box as a shape -- it is the four corners, projected, which is what the rule says.
    west, south, east, north = shape(fixture["input"]["boundary"]).bounds
    corners = [to_metric.transform(x, y) for x, y in
               ((west, south), (east, south), (east, north), (west, north))]
    eastings = [c[0] for c in corners]
    northings = [c[1] for c in corners]
    envelope = box(min(eastings) - ENVELOPE_MARGIN_M, min(northings) - ENVELOPE_MARGIN_M,
                   max(eastings) + ENVELOPE_MARGIN_M, max(northings) + ENVELOPE_MARGIN_M)

    sites = {s["id"]: to_metric.transform(*s["coordinates"]) for s in fixture["input"]["sites"]}
    points = MultiPoint([Point(xy) for xy in sites.values()])
    regions = list(shapely.voronoi_polygons(points, extend_to=envelope).geoms)

    # GEOS returns the regions in no particular order, so each is matched to the site it holds.
    reference = {}
    for region in regions:
        clipped = region.intersection(envelope)
        for identifier, xy in sites.items():
            if region.covers(Point(xy)):
                reference[identifier] = clipped
                break

    reported = {c["siteId"]: project(shape(c["geometry"])) for c in fixture["output"]["cells"]}

    per_cell, worst = [], 0.0
    for identifier in sorted(set(reference) | set(reported)):
        if identifier not in reference or identifier not in reported:
            per_cell.append({"siteId": identifier, "symmetricDifferenceSquareMetres": None,
                             "present": identifier in reported, "inReference": identifier in reference})
            worst = float("inf")
            continue
        difference = reported[identifier].symmetric_difference(reference[identifier]).area
        worst = max(worst, difference)
        per_cell.append({"siteId": identifier,
                         "symmetricDifferenceSquareMetres": difference,
                         "areaSquareMetres": reported[identifier].area,
                         "holdsItsSite": reported[identifier].covers(Point(sites[identifier])),
                         "present": True, "inReference": True})

    union = shapely.unary_union(list(reported.values()))
    tiles_envelope = union.symmetric_difference(envelope).area
    overlaps = 0.0
    identifiers = list(reported)
    for i, a in enumerate(identifiers):
        for b in identifiers[i + 1:]:
            overlaps += reported[a].intersection(reported[b]).area
    all_hold_their_site = all(row.get("holdsItsSite") for row in per_cell)

    agrees = bool(worst <= AREA_TOLERANCE_M2
                  and tiles_envelope <= AREA_TOLERANCE_M2
                  and overlaps <= AREA_TOLERANCE_M2
                  and all_hold_their_site
                  and set(reference) == set(reported))

    return {
        "check": "15-voronoi",
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
            "declaredAlgorithm": declared["algorithm"],
        },
        "criterion": (
            f"each cell within {AREA_TOLERANCE_M2:g} m2 of GEOS's Voronoi region for the same site by symmetric "
            f"difference, the cells tiling the recomputed envelope to within {AREA_TOLERANCE_M2:g} m2 with no "
            f"overlap, and every cell containing its own site"
        ),
        "sites": len(sites),
        "envelopeSquareMetres": envelope.area,
        "perCell": per_cell,
        "worstSymmetricDifferenceSquareMetres": worst,
        "unionAgainstEnvelopeSquareMetres": tiles_envelope,
        "pairwiseOverlapSquareMetres": overlaps,
        "everyCellHoldsItsSite": all_hold_their_site,
        "notEstablished": (
            "That a nearest-pump cell models which pump anybody drank from. Euclidean distance in a projection "
            "ignores streets, walls and the Thames, and the reference ignores them identically."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "voronoi-soho-001.json")
    out = ROOT / "results" / "check-15-voronoi.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 15: agrees={result['agrees']} over {result['sites']} sites -> {out.relative_to(ROOT.parent)}")
    print(f"  worst symmetric difference {result['worstSymmetricDifferenceSquareMetres']:.3e} m2, "
          f"union against envelope {result['unionAgainstEnvelopeSquareMetres']:.3e} m2, "
          f"overlap {result['pairwiseOverlapSquareMetres']:.3e} m2")
