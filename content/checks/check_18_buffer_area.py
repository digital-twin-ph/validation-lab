"""Check 18: Fieldwork Buffer study area against shapely.

**This widget cannot agree exactly with a reference, and this check says so.** Turf buffers in
a local azimuthal equidistant projection; the reference buffers the same boundary in UTM at the
same quadrant count. Those are different projections, so demanding equality would demand
something neither side can deliver. The criterion is a **relative area difference** with the
quadrant count declared.

Two comparisons, criteria fixed before running:

1. **The area**, against a UTM reference buffer at the same 8 segments per quadrant, within
   0.5% relative.
2. **That the buffered boundary contains the original**, which a buffer must.

8 segments per quadrant leaves 0.64% of an ideal circle outside the polygon, against 0.04% at
the 32 this project's `buffer_point` uses. That is ample here and deliberate: this widget
expands a boundary that already exists, so its edge decides nothing. `buffer_point`'s edge
decides membership, which is why it pays for the finer setting. See check 17.

What this cannot establish: whether 500 m is the right distance. The buffered boundary is an
acquisition extent -- it exists so that a network or raster fetched for the study area reaches
past its edge -- and how far past is a judgement about the data being fetched.

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
from shapely.geometry import shape

AREA_TOLERANCE_RELATIVE = 5e-3   # Two different projections; 0.5% is the declared allowance.
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    distance = declared["distanceMetres"]
    steps = declared["stepsPerQuadrant"]

    source = shape(fixture["input"]["boundary"])
    west, south, east, north = source.bounds
    zone = int((west + east) / 2 // 6) + 31
    utm = f"EPSG:{32600 + zone}" if (south + north) / 2 >= 0 else f"EPSG:{32700 + zone}"
    to_utm = pyproj.Transformer.from_crs("OGC:CRS84", utm, always_xy=True)
    project = lambda geometry: shapely.transform(
        geometry, lambda coords: np.column_stack(to_utm.transform(coords[:, 0], coords[:, 1])))

    reference = project(source).buffer(distance, quad_segs=steps)
    reported = project(shape(fixture["output"]["boundary"]))
    relative_area_difference = abs(reported.area - reference.area) / reference.area
    contains_source = reported.covers(project(source))

    agrees = bool(relative_area_difference <= AREA_TOLERANCE_RELATIVE and contains_source)

    return {
        "check": "18-buffer-area",
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
            "declaredProjection": declared["projection"],
        },
        "criterion": (
            f"the buffered area within {AREA_TOLERANCE_RELATIVE:.1%} of a {utm} reference buffer at the same "
            f"{steps} segments per quadrant, and the result containing the original boundary"
        ),
        "distanceMetres": distance,
        "stepsPerQuadrant": steps,
        "referenceCRS": utm,
        "fieldworkAreaSquareMetres": reported.area,
        "referenceAreaSquareMetres": reference.area,
        "sourceAreaSquareMetres": project(source).area,
        "relativeAreaDifference": relative_area_difference,
        "containsTheOriginal": contains_source,
        "notEstablished": (
            "Whether 500 m is the right distance. The buffered boundary is an acquisition extent, and how far "
            "past the study area it should reach is a judgement about the data being fetched. Nor is exact "
            "agreement available or claimed: the two sides buffer in different projections."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "buffer-area-soho-001.json")
    out = ROOT / "results" / "check-18-buffer-area.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 18: agrees={result['agrees']} -> {out.relative_to(ROOT.parent)}")
    print(f"  {result['sourceAreaSquareMetres']:.0f} m2 buffered by {result['distanceMetres']} m -> "
          f"{result['fieldworkAreaSquareMetres']:.0f} m2")
    print(f"  against {result['referenceCRS']}: {result['referenceAreaSquareMetres']:.0f} m2, "
          f"relative difference {result['relativeAreaDifference']:.3e}, "
          f"contains the original: {result['containsTheOriginal']}")
