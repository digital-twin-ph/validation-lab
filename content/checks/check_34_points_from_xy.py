"""Check 34: Fieldwork Point data read from a table, against geopandas.points_from_xy.

Fieldwork's Point data reads a table a workflow computed into points: x from the column named as the longitude, y
from the one named as the latitude, in CRS84. The NYC worked example uses it to place the six ozone monitors whose
daily readings the study averages. Fieldwork experiment 178.

**Genuinely independent.** `geopandas.points_from_xy(x, y, crs="EPSG:4326")` is a separate implementation by separate
authors of the same operation, and the one the practitioner named for it. Its argument order is the thing worth
checking: x first, the longitude.

**Which rows are placed is Fieldwork's declared rule, not geopandas'.** geopandas makes a point from whatever numbers
it is given, including a latitude of 90.0001, and makes an empty point from NaN. Fieldwork keeps a row it cannot place
with no geometry and counts it. So the rule is recomputed here from its own statement -- empty, not a finite number,
|x| > 180 or |y| > 90 -- and geopandas is asked for the points of the rows that pass.

Criteria, fixed before running:

1. The same rows placed and not placed, in order.
2. Every placed point's x and y exactly equal to geopandas' for the same row.
3. The count of distinct positions equal to geopandas' count of distinct (x, y) pairs among placed rows.
4. The CRS geopandas reports is EPSG:4326, with the longitude as x.

What this cannot establish: that a published position is where the monitor stands, nor any CRS but CRS84.
"""
import hashlib
import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import geopandas
import pandas as pd
import shapely

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "points-from-xy-001.json"
RESULT = HERE.parent / "results" / "check-34-points-from-xy.json"


def placeable(x_text, y_text):
    """The declared rule, written here from its statement rather than imported."""
    x_text, y_text = (x_text or "").strip(), (y_text or "").strip()
    if not x_text or not y_text:
        return None
    try:
        x, y = float(x_text), float(y_text)
    except ValueError:
        return None
    if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > 180 or abs(y) > 90:
        return None
    return x, y


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    text = fixture_path.read_text(encoding="utf-8")
    fixture = json.loads(text)
    cases = []
    for case in fixture["output"]["cases"]:
        m = case["mapping"]
        df = pd.DataFrame(case["input"]["rows"])
        rule = [placeable(r.get(m["x"]), r.get(m["y"])) for r in df.to_dict("records")]
        mask = [p is not None for p in rule]
        placed = df[mask]
        geometry = geopandas.points_from_xy(pd.to_numeric(placed[m["x"]].str.strip()),
                                            pd.to_numeric(placed[m["y"]].str.strip()), crs="EPSG:4326")
        gdf = geopandas.GeoDataFrame(placed, geometry=geometry)
        reference = iter([(pt.x, pt.y) for pt in gdf.geometry])
        expected = [next(reference) if ok else None for ok in mask]
        produced = [tuple(f["coordinates"]) if f["coordinates"] else None for f in case["output"]["features"]]
        unplaced_fw = [u["row"] for u in case["output"]["unplaced"]]
        unplaced_rule = [i + 1 for i, ok in enumerate(mask) if not ok]
        differing = [i + 1 for i, (a, b) in enumerate(zip(produced, expected)) if a != b]
        distinct = len({(pt.x, pt.y) for pt in gdf.geometry})
        agrees = bool(len(produced) == len(expected) and not differing and unplaced_fw == unplaced_rule
                      and distinct == case["output"]["positions"] and gdf.crs.to_epsg() == 4326)
        cases.append({"note": case["note"], "rows": len(df), "placed": int(sum(mask)),
                      "unplaced": {"fieldwork": unplaced_fw, "declaredRule": unplaced_rule},
                      "rowsWhoseCoordinatesDiffer": differing,
                      "distinctPositions": {"fieldwork": case["output"]["positions"], "geopandas": distinct},
                      "crs": gdf.crs.to_string(), "agrees": agrees})
    return {
        "check": "34-points-from-xy",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {"runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
                        "isPyodide": sys.platform == "emscripten", "geopandas": geopandas.__version__,
                        "shapely": shapely.__version__, "pandas": pd.__version__},
        "fixture": {"id": fixture.get("fixtureId"), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": "the same rows placed and not placed; every placed x and y exactly geopandas.points_from_xy's; "
                     "the same count of distinct positions; CRS EPSG:4326 with the longitude as x",
        "cases": cases,
        "notEstablished": ["That a published position is where the monitor stands: it is the custodian's claim.",
                           "Any CRS but CRS84."],
        "agrees": all(c["agrees"] for c in cases),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["cases"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['placed']} of {c['rows']} placed, "
              f"{c['distinctPositions']['fieldwork']} positions  {c['note']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
