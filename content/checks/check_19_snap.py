"""Check 19: Fieldwork Snap sites to the network against pyproj.

The first step of the isochrone chain. A snap is a nearest-neighbour search and a distance,
both exact: there is no tolerance to argue about, and a disagreement would be a disagreement
about the projection or about which node is nearest.

Four comparisons, criteria fixed before running:

1. **The node chosen** for each site, exactly. The reference projects the sites and the 738
   network nodes with pyproj and takes the smallest Euclidean distance.
2. **The distance moved**, to half a centimetre -- which is the finest a comparison can be,
   because the widget reports `snapDistanceM` as `Number(d.toFixed(2))`. It computes in full
   precision and *publishes* centimetres, so 5 mm is half of its last reported digit and not a
   statement about its accuracy. The first version of this check asked for 1 mm and failed at
   3.7 mm, which was rounding and nothing else: the criterion had not read what the widget
   says it reports.
3. **The returned position**, which must be the chosen node's position and not the site's --
   that is what snapping means.
4. **That no site exceeded the snap limit**, which the widget refuses rather than snapping.

**Ties are reported whether or not any exist.** Two nodes exactly equidistant from a site would
make the choice arbitrary, and a check that passed without saying so would be hiding the one
case where the two implementations could legitimately differ. The margin between the nearest
and second-nearest node is reported per site for the same reason.

What this cannot establish: that snapping is harmless. It moves the site. Everything downstream
starts from the junction rather than from where the pump actually stood, and the distances here
are 2.2 to 20.9 m -- small against a 375 m five-minute budget, and not nothing. Both
implementations move it identically.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import pyproj

# Half of the widget's last reported digit: snapDistanceM is Number(d.toFixed(2)).
DISTANCE_TOLERANCE_M = 5e-3
POSITION_TOLERANCE_DEG = 1e-12
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    forward = pyproj.Transformer.from_crs("OGC:CRS84", declared["metricCRS"], always_xy=True)
    limit = declared["maxSnapM"]

    nodes = {n["id"]: forward.transform(*n["coordinates"]) for n in fixture["input"]["network"]["nodes"]}
    node_positions = {n["id"]: n["coordinates"] for n in fixture["input"]["network"]["nodes"]}
    reported = {s["id"]: s for s in fixture["output"]["snapped"]}

    per_site, ties, worst_distance_error, worst_position_error = [], 0, 0.0, 0.0
    beyond_limit = []
    for site in fixture["input"]["sites"]:
        easting, northing = forward.transform(*site["coordinates"])
        ranked = sorted(((((easting - x) ** 2 + (northing - y) ** 2) ** 0.5, identifier)
                         for identifier, (x, y) in nodes.items()))
        nearest_distance, nearest = ranked[0]
        runner_up_distance = ranked[1][0]
        margin = runner_up_distance - nearest_distance
        if margin == 0:
            ties += 1
        if nearest_distance > limit:
            beyond_limit.append(site["id"])

        row = reported.get(site["id"], {})
        node_agrees = row.get("networkNodeId") == nearest
        distance_error = abs((row.get("snapDistanceM") or 0) - nearest_distance)
        expected_position = node_positions[nearest]
        reported_position = row.get("coordinates") or [None, None]
        position_error = (max(abs(reported_position[0] - expected_position[0]),
                              abs(reported_position[1] - expected_position[1]))
                          if reported_position[0] is not None else float("inf"))
        worst_distance_error = max(worst_distance_error, distance_error)
        worst_position_error = max(worst_position_error, position_error)
        per_site.append({
            "id": site["id"], "name": site["name"],
            "referenceNode": nearest, "fieldworkNode": row.get("networkNodeId"),
            "nodeAgrees": node_agrees,
            "referenceDistanceM": nearest_distance, "fieldworkDistanceM": row.get("snapDistanceM"),
            "distanceErrorM": distance_error,
            "marginToSecondNearestM": margin,
            "positionIsTheNodeNotTheSite": position_error <= POSITION_TOLERANCE_DEG,
        })

    nodes_agree = all(row["nodeAgrees"] for row in per_site)
    positions_agree = all(row["positionIsTheNodeNotTheSite"] for row in per_site)
    counts_agree = (fixture["output"]["siteCount"] == len(fixture["input"]["sites"])
                    and fixture["output"]["snappedNodeCount"] == len({row["referenceNode"] for row in per_site}))
    greatest = max(row["referenceDistanceM"] for row in per_site)
    greatest_agrees = abs(fixture["output"]["greatestSnapDistanceMetres"] - greatest) <= 0.005

    agrees = bool(nodes_agree and positions_agree and counts_agree and greatest_agrees
                  and worst_distance_error <= DISTANCE_TOLERANCE_M and not beyond_limit)

    return {
        "check": "19-snap",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pyproj": pyproj.__version__,
            "proj": pyproj.proj_version_str,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredRule": declared["rule"],
        },
        "criterion": (
            f"the same node chosen for every site, the distance moved within {DISTANCE_TOLERANCE_M:g} m -- half "
            f"of the centimetre the widget reports it to -- the "
            f"returned position being the node's and not the site's, the site and distinct-node counts exact, "
            f"and no site beyond the {limit} m limit"
        ),
        "sites": len(fixture["input"]["sites"]),
        "networkNodes": len(nodes),
        "perSite": per_site,
        "nodesAgree": nodes_agree,
        "positionsAreTheNodes": positions_agree,
        "countsAgree": counts_agree,
        "greatestDistanceAgrees": greatest_agrees,
        "worstDistanceErrorMetres": worst_distance_error,
        "reportedPrecisionM": 0.01,
        "worstPositionErrorDegrees": worst_position_error,
        "equidistantTies": ties,
        "smallestMarginToSecondNearestM": min(row["marginToSecondNearestM"] for row in per_site),
        "sitesBeyondTheLimit": beyond_limit,
        "notEstablished": (
            "That snapping is harmless. It moves the site: everything downstream starts from the junction "
            "rather than from where the pump stood, by 2.2 to 20.9 m here against a 375 m five-minute budget. "
            "Both implementations move it identically."
        ),
        "agrees": agrees,
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "snap-soho-001.json")
    out = ROOT / "results" / "check-19-snap.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 19: agrees={result['agrees']} over {result['sites']} sites against "
          f"{result['networkNodes']} nodes -> {out.relative_to(ROOT.parent)}")
    print(f"  nodes agree: {result['nodesAgree']}, worst distance error "
          f"{result['worstDistanceErrorMetres']:.3e} m against a reported precision of "
          f"{result['reportedPrecisionM']} m, ties: {result['equidistantTies']}, "
          f"smallest margin to the second nearest {result['smallestMarginToSecondNearestM']:.2f} m")
