"""Check 12: Fieldwork Combined area against shapely.

Fieldwork unions polygons with polyclip-ts and measures the result with a shoelace sum.
shapely unions with GEOS and measures with GEOS. The two are independent implementations of
the same operation, which is the point: a union is where two libraries most plausibly differ,
because it is where coincident edges and near-degenerate intersections get decided.

Three comparisons, criteria fixed before running:

1. **The combined geometry**, by symmetric difference against shapely's union.
2. **The combined area**, which is what the widget reports and a reader acts on.
3. **The summed area of the parts, net of holes.** Net matters: a single hole-bearing
   corridor otherwise reads as overlapping itself, which is the defect Fieldwork's own
   comment records finding on the isochrone chain's union step.

The fixture is three nested bands' corridors -- 2, 5 and 10 minutes from the Broad Street
pump. Nested is deliberate: a shorter band's corridor lies inside a longer one's, so the
parts overlap heavily and the combined area is far smaller than their sum. A fixture of
disjoint parts would have made the union trivially equal to the sum and checked nothing.

What this cannot establish: that the combined area means what a reader will take it to mean.
It is distinct ground covered by at least one corridor, which is not a population, not a
catchment, and not a service area.

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
from shapely.geometry import MultiPolygon, shape

AREA_TOLERANCE_M2 = 1.0   # A union of 940,000 m2 of overlapping corridors; 1 m2 is 1 part per million.
ROOT = Path(__file__).resolve().parent.parent


def parts_of(geometry):
    shaped = shape(geometry)
    return list(shaped.geoms) if isinstance(shaped, MultiPolygon) else [shaped]


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    transformer = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)
    # shapely.transform with a coordinate-array callback, matching check 08.
    # shapely.ops.transform is deprecated and emits a warning into a check's own output.
    def project(geometry):
        return shapely.transform(
            geometry, lambda coords: np.column_stack(transformer.transform(coords[:, 0], coords[:, 1])))

    projected_parts = [project(part)
                       for polygon in fixture["input"]["polygons"]
                       for part in parts_of(polygon["geometry"])]
    parts_area = sum(part.area for part in projected_parts)   # shapely's area is net of holes
    reference = shapely.unary_union(projected_parts)
    reference_pieces = len(reference.geoms) if isinstance(reference, MultiPolygon) else 1

    reported = fixture["output"]
    reported_geometry = shapely.unary_union([project(part) for part in parts_of(reported["geometry"])])
    geometry_difference = reported_geometry.symmetric_difference(reference).area

    combined_difference = abs(reported["combinedAreaSquareMetres"] - reference.area)
    parts_difference = abs(reported["partsAreaSquareMetres"] - parts_area)
    pieces_agree = reported["combinedPieceCount"] == reference_pieces
    part_count_agrees = reported["partCount"] == len(projected_parts)

    agrees = bool(
        geometry_difference <= AREA_TOLERANCE_M2
        and combined_difference <= AREA_TOLERANCE_M2
        and parts_difference <= AREA_TOLERANCE_M2
        and pieces_agree
        and part_count_agrees
    )

    return {
        "check": "12-combined-area",
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
            f"the combined geometry within {AREA_TOLERANCE_M2:g} m2 by symmetric difference, the combined "
            f"area and the summed parts area each within {AREA_TOLERANCE_M2:g} m2, and the part and piece "
            f"counts unchanged"
        ),
        "parts": len(projected_parts),
        "reference": {"combinedAreaSquareMetres": reference.area, "partsAreaSquareMetres": parts_area,
                      "combinedPieceCount": reference_pieces},
        "fieldwork": {"combinedAreaSquareMetres": reported["combinedAreaSquareMetres"],
                      "partsAreaSquareMetres": reported["partsAreaSquareMetres"],
                      "combinedPieceCount": reported["combinedPieceCount"]},
        "geometryDifferenceSquareMetres": geometry_difference,
        "combinedAreaDifferenceSquareMetres": combined_difference,
        "partsAreaDifferenceSquareMetres": parts_difference,
        "pieceCountAgrees": pieces_agree,
        "partCountAgrees": part_count_agrees,
        "overlapSquareMetres": parts_area - reference.area,
        "notEstablished": (
            "That the combined area means what a reader will take it to mean. It is distinct ground covered "
            "by at least one corridor: not a population, not a catchment, not a service area."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "combined-area-soho-001.json")
    out = ROOT / "results" / "check-12-combined-area.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 12: agrees={result['agrees']} over {result['parts']} parts -> {out.relative_to(ROOT.parent)}")
    print(f"  combined {result['fieldwork']['combinedAreaSquareMetres']:.0f} m2 vs "
          f"{result['reference']['combinedAreaSquareMetres']:.0f} m2 "
          f"(difference {result['combinedAreaDifferenceSquareMetres']:.3e} m2), "
          f"overlap {result['overlapSquareMetres']:.0f} m2")
