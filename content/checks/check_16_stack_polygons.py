"""Check 16: Fieldwork Collect polygon layers against an independent sort.

This widget does one thing: concatenate polygon layers and order the result largest extent
first, so a smaller band draws on top of a larger one. There is no geometry to compare, which
makes the check a check of a *rule* rather than of arithmetic -- and the rule is deliberately
crude in a way worth pinning down.

**Extent is not area.** It is the sum over every ring of a polygon -- outer and interior alike
-- of the absolute shoelace area of that ring, in **square degrees**, with no projection, and
holes added rather than subtracted. That makes it a sort key and nothing else. Fieldwork's own
comment says so: `summarize_hull` and `summarize_combined_area` take a UTM zone because they
report areas, and this widget does not take one because it does not.

Three comparisons, criteria fixed before running:

1. **The order of identifiers**, exactly, recomputed from the declared extent rule.
2. **That nothing was added, dropped or merged**: the same multiset of identifiers in and out.
3. **The counts the widget reports**: layers, polygons, and polygons carrying a band.

The reference computes extent with shapely's `area` on each ring taken as its own polygon,
which adds holes positively because a ring is just a ring once separated from its parent. That
is the same quantity by a different route.

What this cannot establish: that largest-first is the right draw order, or that a reader will
not mistake the extent for a measurement. The second is a real risk and the reason the fixture
declares the rule in full.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import shapely
from shapely.geometry import MultiPolygon, Polygon, shape

ROOT = Path(__file__).resolve().parent.parent


def extent_of(geometry) -> float:
    """Sum of every ring's absolute area, in square degrees, holes counted positively."""
    shaped = shape(geometry)
    parts = list(shaped.geoms) if isinstance(shaped, MultiPolygon) else [shaped]
    total = 0.0
    for part in parts:
        total += abs(Polygon(part.exterior).area)
        for interior in part.interiors:
            total += abs(Polygon(interior).area)
    return total


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["computationCRS"] != "OGC:CRS84":
        raise SystemExit(f"Unexpected computation CRS {declared['computationCRS']}")

    incoming = [(polygon["id"], polygon.get("minutes"), extent_of(polygon["geometry"]))
                for layer in fixture["input"]["layers"] for polygon in layer["polygons"]]
    reference_order = [identifier for identifier, _minutes, _extent
                       in sorted(incoming, key=lambda row: -row[2])]

    reported_order = fixture["output"]["order"]
    order_agrees = reported_order == reference_order
    same_polygons = Counter(reported_order) == Counter(identifier for identifier, _, _ in incoming)

    banded = sum(1 for _identifier, minutes, _extent in incoming if minutes is not None)
    counts_agree = (fixture["output"]["layerCount"] == len(fixture["input"]["layers"])
                    and fixture["output"]["polygonCount"] == len(incoming)
                    and fixture["output"]["bandedPolygonCount"] == banded)

    # Ties would make the order ambiguous, so whether any exist is part of the result.
    extents = sorted((extent for _i, _m, extent in incoming), reverse=True)
    ties = sum(1 for a, b in zip(extents, extents[1:]) if a == b)

    agrees = bool(order_agrees and same_polygons and counts_agree)

    return {
        "check": "16-stack-polygons",
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
            "declaredRule": declared["extentRule"],
        },
        "criterion": (
            "the order of identifiers exactly as the declared extent rule gives it, the same multiset of "
            "identifiers in and out, and the layer, polygon and banded-polygon counts exact"
        ),
        "layers": len(fixture["input"]["layers"]),
        "polygons": len(incoming),
        "extents": [{"id": identifier, "minutes": minutes, "extentSquareDegrees": extent}
                    for identifier, minutes, extent in sorted(incoming, key=lambda row: -row[2])],
        "referenceOrder": reference_order,
        "fieldworkOrder": reported_order,
        "orderAgrees": order_agrees,
        "samePolygonsInAndOut": same_polygons,
        "countsAgree": counts_agree,
        "extentTies": ties,
        "notEstablished": (
            "That largest-first is the right draw order, or that a reader will not mistake the extent for a "
            "measurement of ground. It is unprojected and counts holes positively, so it is a sort key only."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "stack-polygons-soho-001.json")
    out = ROOT / "results" / "check-16-stack-polygons.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 16: agrees={result['agrees']} over {result['polygons']} polygons in "
          f"{result['layers']} layers -> {out.relative_to(ROOT.parent)}")
    print(f"  order agrees: {result['orderAgrees']}, ties in extent: {result['extentTies']}")
    for row in result["extents"]:
        print(f"    {row['id']:<28} {row['extentSquareDegrees']:.3e} square degrees")
