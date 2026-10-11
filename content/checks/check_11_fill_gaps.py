"""Check 11: Fieldwork Fill interior gaps against shapely.

Dropping a polygon's interior rings is exact, so the comparison is about whether Fieldwork
drops the right rings and reports the right areas -- not about tolerance.

Four comparisons, criteria fixed before running:

1. **The filled geometry**, part by part, as shapely's `Polygon(part.exterior)`.
2. **The number of gaps filled**, which is the count of interior rings across all parts.
3. **The area before**, net of holes, and **the area after**, the outer rings alone.
4. **The area added**, which is the figure that matters: it is ground the traversal never
   computed as reachable and the fill now claims.

What this cannot establish: whether filling is the right thing to do. It is not a question
with a numerical answer. Fieldwork's own note says the added ground "was never computed as
covered" and that filling "asserts the opposite" of whatever the gaps meant -- and the
reference implementation asserts exactly the same thing, because it is the same operation.

Independent by construction: nothing here imports Fieldwork code. The projection is done
here with pyproj, so the areas are recomputed rather than taken on trust.

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
from shapely.geometry import MultiPolygon, Polygon, shape

AREA_TOLERANCE_M2 = 0.05      # Fieldwork reports areas to two decimals.
GEOMETRY_TOLERANCE_M2 = 0.05  # Symmetric difference between the two filled geometries.
ROOT = Path(__file__).resolve().parent.parent


def parts_of(geometry):
    """Every polygon in a geometry, whether it arrived as a Polygon or a MultiPolygon."""
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

    gaps = 0
    area_before = 0.0
    area_after = 0.0
    reference_filled = []
    for polygon in fixture["input"]["polygons"]:
        for part in parts_of(polygon["geometry"]):
            projected = project(part)
            gaps += len(projected.interiors)
            area_before += projected.area                     # shapely's area is already net of holes
            outer = Polygon(projected.exterior)
            area_after += outer.area
            reference_filled.append(outer)

    reported = fixture["output"]
    reported_parts = [project(part)
                      for polygon in reported["polygons"]
                      for part in parts_of(polygon["geometry"])]

    # Compared by symmetric difference rather than vertex by vertex: the same filled polygon
    # may legitimately be expressed as a Polygon or a one-part MultiPolygon, with its ring
    # starting anywhere. Area disagreement is what would matter.
    reported_union = shapely.unary_union(reported_parts)
    reference_union = shapely.unary_union(reference_filled)
    geometry_difference = reported_union.symmetric_difference(reference_union).area

    gaps_agree = reported["gapsFilled"] == gaps
    before_difference = abs(reported["areaBeforeSquareMetres"] - area_before)
    after_difference = abs(reported["areaAfterSquareMetres"] - area_after)
    added_difference = abs(reported["areaAddedSquareMetres"] - (area_after - area_before))
    interiors_remaining = sum(len(part.interiors) for part in reported_parts)

    agrees = bool(
        gaps_agree
        and interiors_remaining == 0
        and geometry_difference <= GEOMETRY_TOLERANCE_M2
        and max(before_difference, after_difference, added_difference) <= AREA_TOLERANCE_M2
    )

    return {
        "check": "11-fill-gaps",
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
            f"the same number of gaps filled, no interior ring left in the output, the filled geometry "
            f"within {GEOMETRY_TOLERANCE_M2:g} m2 by symmetric difference, and the areas before, after and "
            f"added each within {AREA_TOLERANCE_M2:g} m2"
        ),
        "parts": len(reported_parts),
        "reference": {"gapsFilled": gaps, "areaBeforeSquareMetres": area_before,
                      "areaAfterSquareMetres": area_after, "areaAddedSquareMetres": area_after - area_before},
        "fieldwork": {"gapsFilled": reported["gapsFilled"],
                      "areaBeforeSquareMetres": reported["areaBeforeSquareMetres"],
                      "areaAfterSquareMetres": reported["areaAfterSquareMetres"],
                      "areaAddedSquareMetres": reported["areaAddedSquareMetres"]},
        "gapsAgree": gaps_agree,
        "interiorRingsRemaining": interiors_remaining,
        "geometryDifferenceSquareMetres": geometry_difference,
        "areaBeforeDifferenceSquareMetres": before_difference,
        "areaAfterDifferenceSquareMetres": after_difference,
        "areaAddedDifferenceSquareMetres": added_difference,
        "notEstablished": (
            "Whether filling is the right thing to do. The added ground was never computed as reachable, "
            "and the reference asserts it identically because it is the same operation."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "fill-gaps-soho-001.json")
    out = ROOT / "results" / "check-11-fill-gaps.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 11: agrees={result['agrees']} over {result['parts']} parts -> {out.relative_to(ROOT.parent)}")
    print(f"  gaps {result['fieldwork']['gapsFilled']} vs {result['reference']['gapsFilled']}, "
          f"area added {result['fieldwork']['areaAddedSquareMetres']:.0f} m2 "
          f"(difference {result['areaAddedDifferenceSquareMetres']:.3e} m2)")
