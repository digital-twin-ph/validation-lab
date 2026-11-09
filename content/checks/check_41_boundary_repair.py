"""Check 41: Fieldwork's boundary repair against shapely.

Fieldwork experiment 194 made the study area remove two faults from a published boundary as it is read: a vertex
equal to the one before it, and the tip of a zero-width spike, where the outline goes out along a line and comes
straight back. Every removal is listed by kind and position. Found on OCHA COD-AB's 16 districts of Sierra Leone, 84
repeated vertices and one spike in Bonthe. Here, those districts and geoBoundaries' 92 municipalities of Rio de Janeiro
state, a level that loaded before the repair existed.

**Independent.** The repeats are removed by shapely's `remove_repeated_points` (GEOS, C++), and what it dropped is
read off by comparing its ring with the published one. The spike rule has no shapely equivalent, so it is written out
here from the fixture's declared order and on-segment test, in Python. Areas and validity are GEOS's. Nothing of
Fieldwork's code is read.

Criteria, fixed before running:

1. **Every repeated vertex**: the positions shapely drops, ring by ring, equal Fieldwork's `repeated` removals, in order.
2. **Every spike tip**: the rule written out here removes the same positions as Fieldwork's `spike` removals, in order.
3. **Every vertex count**, published and repaired, equal.
4. **No area changes**: GEOS's area of each repaired unit within 1e-12 square degrees of the published one.

Recorded, not asserted: GEOS's validity of each unit before and after, with its reason; and any spike the exact
(rational) on-segment test would decide differently from the declared 1e-12 tolerance.

What this cannot establish: that the published boundaries have no other fault. A ring crossing itself is not
repaired, and GEOS's verdict on what is left is recorded for that reason. Nor that a spike is a digitising error: it
encloses no area, which is why it can be removed, and nothing here knows why it was drawn.

Design record: fieldwork/docs/experiments/194-the-boundary-repair.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone
from fractions import Fraction

import shapely
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.validation import explain_validity
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "boundary-repair-001.json"
RESULT = HERE.parent / "results" / "check-41-boundary-repair.json"
EPS = 1e-12
AREA_TOLERANCE = 1e-12


def polygons(geometry: dict) -> list[list[list[list[float]]]]:
    return [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]


def repeats_by_shapely(ring: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    """The ring shapely keeps, and the positions it dropped, read off in order against the published ring."""
    kept = [list(p) for p in shapely.remove_repeated_points(shapely.linearrings(ring), tolerance=0).coords]
    dropped, j = [], 0
    for p in ring:
        if j < len(kept) and p[0] == kept[j][0] and p[1] == kept[j][1]:
            j += 1
        else:
            dropped.append(list(p))
    return kept, dropped


def on_segment(a, b, p, exact: bool) -> bool:
    if exact:
        a, b, p = ([Fraction(v) for v in q] for q in (a, b, p))
        eps = 0
    else:
        eps = EPS
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    inside = cross == 0 if exact else abs(cross) < eps
    return inside and min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps \
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps


def spikes(ring: list[list[float]], exact: bool = False) -> tuple[list[list[float]], list[list[float]]]:
    """The declared order: on the ring without its closing vertex, read cyclically, the first i where c lies on ab or
    a lies on bc removes b; from the start again, until none is found or three vertices are left."""
    pts, removed = ring[:-1], []
    changed = True
    while changed and len(pts) > 3:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
            if on_segment(a, b, c, exact) or on_segment(b, c, a, exact):
                removed.append(list(b))
                pts = [q for k, q in enumerate(pts) if k != (i + 1) % n]
                changed = True
                break
    return pts + [pts[0]], removed


def as_geometry(parts: list[list[list[list[float]]]]):
    built = [Polygon(rings[0], rings[1:]) for rings in parts]
    return built[0] if len(built) == 1 else MultiPolygon(built)


def unit_check(feature: dict, theirs: dict) -> dict:
    repeated, spiked, inexact, repaired = [], [], [], []
    for rings in polygons(feature["geometry"]):
        out = []
        for ring in rings:
            kept, dropped = repeats_by_shapely(ring)
            repeated += dropped
            left, tips = spikes(kept)
            spiked += tips
            if spikes(kept, exact=True)[1] != tips:
                inexact.append({"declared": tips, "exact": spikes(kept, exact=True)[1]})
            out.append(left)
        repaired.append(out)
    published = shape(feature["geometry"])
    after = as_geometry(repaired)
    count = lambda parts: sum(len(r) for rings in parts for r in rings)
    fw_repeated = [r["at"] for r in theirs["repairs"] if r["kind"] == "repeated"]
    fw_spike = [r["at"] for r in theirs["repairs"] if r["kind"] == "spike"]
    area_change = abs(after.area - published.area)
    checks = {
        "repeated": repeated == fw_repeated,
        "spike": spiked == fw_spike,
        "vertices": count(polygons(feature["geometry"])) == theirs["publishedVertices"]
                    and count(repaired) == theirs["repairedVertices"],
        "area": area_change <= AREA_TOLERANCE,
    }
    return {"name": feature["name"], "agrees": all(checks.values()), "checks": checks,
            "shapely": {"repeated": len(repeated), "spike": spiked},
            "fieldwork": {"repeated": len(fw_repeated), "spike": fw_spike},
            "vertices": {"published": theirs["publishedVertices"], "repaired": theirs["repairedVertices"]},
            "areaChange": area_change,
            "geosBefore": explain_validity(published), "geosAfter": explain_validity(after),
            "fieldworkBefore": theirs["checkBefore"], "fieldworkAfter": theirs["checkAfter"],
            "inexact": inexact}


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    outputs = {level["id"]: level for level in fixture["output"]["levels"]}
    levels = []
    for level in fixture["input"]["levels"]:
        theirs = outputs[level["id"]]["units"]
        units = [unit_check(f, t) for f, t in zip(level["features"], theirs)]
        levels.append({
            "id": level["id"], "source": level["source"], "units": len(units),
            "agrees": all(u["agrees"] for u in units) and len(units) == len(theirs),
            "repaired": sum(1 for u in units if u["shapely"]["repeated"] or u["shapely"]["spike"]),
            "repeated": sum(u["shapely"]["repeated"] for u in units),
            "spikes": sum(len(u["shapely"]["spike"]) for u in units),
            "geosInvalidBefore": sum(1 for u in units if u["geosBefore"] != "Valid Geometry"),
            "geosInvalidAfter": [{"name": u["name"], "reason": u["geosAfter"]} for u in units if u["geosAfter"] != "Valid Geometry"],
            "differs": [u for u in units if not u["agrees"]],
            "inexact": [{"name": u["name"], **x} for u in units for x in u["inexact"]],
            "repairedUnits": [{k: u[k] for k in ("name", "shapely", "fieldwork", "vertices", "areaChange", "geosBefore", "geosAfter")}
                              for u in units if u["shapely"]["repeated"] or u["shapely"]["spike"]],
        })
    return {
        "check": "41-boundary-repair",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": all(level["agrees"] for level in levels),
        "criteria": "repeated vertices equal to shapely.remove_repeated_points, in order; spike tips equal to the "
                    "declared rule written out here, in order; vertex counts equal; GEOS area unchanged within 1e-12",
        "levels": levels,
        "notEstablished": [
            "That the published boundaries have no other fault: a ring crossing itself is not repaired; GEOS's verdict on what is left is recorded.",
            "That a spike is a digitising error: it encloses no area, which is why it can be removed.",
            "How often the repair runs on geoBoundaries in general: one level of one country is here.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "shapely": shapely.__version__, "geos": shapely.geos_version_string,
                        "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
