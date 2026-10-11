"""Check 07: Fieldwork Reachable junctions against NetworkX.

NetworkX is the right reference here rather than a convenience: the case study this
widget was derived from reaches its isochrones with `nx.ego_graph(..., distance=...)`,
so the comparison is against the implementation the original analysis used.

Two comparisons, both with criteria fixed before running:

1. The set of reached nodes, compared exactly. A node either is or is not within the
   budget, so there is no tolerance to give.
2. The cheapest cost to each reached node, in metres. The tolerance is the rounding
   Fieldwork applies to the attribute it reports, not an allowance for disagreement.

The traversal runs on the edge lengths stated in the fixture. Neither implementation
measures geometry, so this cannot establish that those lengths are right -- only that
two traversals over the same lengths agree.

What this cannot establish: that the reached set is what anyone can walk in five
minutes. The budget is 375 m because the case study assumes 4.5 km/h for pedestrians
in Soho in 1854, and both implementations inherit that assumption identically.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/83-reachable-junctions.md
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture, verified_asset

import networkx as nx

# Fieldwork rounds the reported cost to two decimals, so agreement is asserted at the
# precision it publishes. A tighter tolerance would be measuring its rounding.
COST_TOLERANCE_M = 1e-2
ROOT = Path(__file__).resolve().parent.parent




def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    if declared["direction"] != "outbound":
        raise SystemExit(f"This check covers outbound traversal only, not {declared['direction']}")
    if declared["costAttribute"] != "lengthM":
        raise SystemExit(f"Unexpected cost attribute {declared['costAttribute']}")

    budget = declared["budgetMetres"]
    if budget != declared["minutes"] * declared["speedMPerMin"]:
        raise SystemExit("Declared budget is not the minutes times the speed")

    graph = nx.DiGraph()
    for node in fixture["input"]["network"]["nodes"]:
        graph.add_node(node["id"])
    for edge in fixture["input"]["network"]["edges"]:
        # A repeated pair keeps the shorter street, which is what a cheapest-path
        # traversal over a multigraph would use.
        existing = graph.get_edge_data(edge["from"], edge["to"], default=None)
        if existing is None or edge["lengthM"] < existing["length"]:
            graph.add_edge(edge["from"], edge["to"], length=edge["lengthM"])

    reference = nx.single_source_dijkstra_path_length(
        graph, declared["originNodeId"], cutoff=budget, weight="length"
    )

    reported = {r["networkNodeId"]: r["travelMetres"] for r in fixture["output"]["reached"]}
    reference_only = sorted(set(reference) - set(reported))
    fieldwork_only = sorted(set(reported) - set(reference))
    sets_agree = not reference_only and not fieldwork_only

    differences = {n: abs(reported[n] - reference[n]) for n in set(reported) & set(reference)}
    worst_node = max(differences, key=differences.get) if differences else None
    worst = differences[worst_node] if worst_node else 0.0
    costs_agree = worst <= COST_TOLERANCE_M

    # The budget left at a node is what the corridor step consumes downstream, so it is
    # checked too: it must be the budget less the cost, at the same precision.
    remaining = {r["networkNodeId"]: r["remainingM"] for r in fixture["output"]["reached"]}
    worst_remaining = max(
        (abs(remaining[n] - (budget - reference[n])) for n in set(remaining) & set(reference)),
        default=0.0,
    )
    remaining_agrees = worst_remaining <= COST_TOLERANCE_M

    return {
        "check": "07-reachability",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "networkx": nx.__version__,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredMethod": declared["method"],
        },
        "criterion": (
            f"the same set of reached nodes exactly, every cost within {COST_TOLERANCE_M:g} m, "
            f"and every remaining budget within {COST_TOLERANCE_M:g} m of the budget less the cost"
        ),
        "networkNodes": len(fixture["input"]["network"]["nodes"]),
        "networkEdges": len(fixture["input"]["network"]["edges"]),
        "budgetMetres": budget,
        "reference": {"implementation": "networkx.single_source_dijkstra_path_length", "reached": len(reference)},
        "fieldwork": {"reached": len(reported)},
        "reachedOnlyByReference": reference_only,
        "reachedOnlyByFieldwork": fieldwork_only,
        "setsAgree": sets_agree,
        "worstCostDifferenceM": worst,
        "worstCostDifferenceNode": worst_node,
        "costsAgree": costs_agree,
        "worstRemainingDifferenceM": worst_remaining,
        "remainingAgrees": remaining_agrees,
        "notEstablished": (
            "Whether the reached set is what anyone can walk in five minutes. The 375 m budget "
            "comes from assuming 4.5 km/h for pedestrians in Soho in 1854, and both "
            "implementations inherit that assumption identically. The edge lengths are taken as "
            "supplied by both, so neither checks the other's geometry."
        ),
        "agrees": bool(sets_agree and costs_agree and remaining_agrees),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "reachability-soho-001.json")
    out = ROOT / "results" / "check-07-reachability.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 07: agrees={result['agrees']} over {result['networkNodes']} nodes -> {out.relative_to(ROOT.parent)}")
    print(f"  reached {result['fieldwork']['reached']} vs reference {result['reference']['reached']}; "
          f"worst cost difference {result['worstCostDifferenceM']:.3e} m")
