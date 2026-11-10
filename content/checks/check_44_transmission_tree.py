"""Check 44: Fieldwork's transmission tree for Hagelloch, 1861, against networkx.

Fieldwork experiment 200 draws who infected whom as chains over time: Chart, set to Transmission tree, places each of
the 188 cases in a chain, at a generation, on a row. The fixture is that computation run through Fieldwork's own code.

**Independent.** Here the same three columns build a directed graph in networkx, infector to case. Chains are its weakly
connected components, each started by its root (a case naming no infector, or one the table does not hold); a case's
generation is one more than its shortest path length from the root. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **The same chains**: every case in the chain started by the same root, and the same chain sizes.
2. **The same generation** for every case.
3. **The rows are a valid order**: every case below its infector, and every chain's cases on consecutive rows.
4. **The same counts**: cases, chains, links, and cases naming no infector.

What this cannot establish: who infected whom. Both sides read the 1861 reconstruction in the infector column.

Design record: fieldwork/docs/experiments/200-operational-epidemiology.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import networkx

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "tree-hagelloch-001.json"
RESULT = HERE.parent / "results" / "check-44-transmission-tree.json"


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    cases = fixture["input"]["cases"]
    ids = {c["case_ID"] for c in cases}
    graph = networkx.DiGraph()
    graph.add_nodes_from(ids)
    for c in cases:
        if c["infector"] and c["infector"] in ids and c["infector"] != c["case_ID"]:
            graph.add_edge(c["infector"], c["case_ID"])
    roots = {n for n in graph.nodes if graph.in_degree(n) == 0}

    chain_of, generation_of = {}, {}
    for root in roots:
        for node, depth in networkx.single_source_shortest_path_length(graph, root).items():
            chain_of[node] = root
            generation_of[node] = depth + 1
    sizes = {}
    for root in chain_of.values():
        sizes[root] = sizes.get(root, 0) + 1

    out = {c["case_ID"]: c for c in fixture["output"]["cases"]}
    differs = []
    for case_id in ids:
        got = out.get(case_id)
        problems = []
        if got is None:
            problems.append("not drawn")
        else:
            if got["chain"] != chain_of.get(case_id):
                problems.append(f"chain {got['chain']} != {chain_of.get(case_id)}")
            if got["generation"] != generation_of.get(case_id):
                problems.append(f"generation {got['generation']} != {generation_of.get(case_id)}")
        if problems:
            differs.append({"case_ID": case_id, "problems": problems})

    row = {k: v["row"] for k, v in out.items()}
    below = all(row[child] > row[parent] for parent, child in graph.edges)
    consecutive = all(
        max(row[n] for n in members) - min(row[n] for n in members) + 1 == len(members)
        for members in ({n for n, r in chain_of.items() if r == root} for root in roots))
    counts = {"cases": len(ids), "chains": len(roots), "links": graph.number_of_edges(),
              "noInfector": sum(1 for c in cases if not c["infector"])}
    theirs = fixture["output"]["counts"]
    counts_agree = all(theirs[k] == v for k, v in counts.items())
    sizes_agree = sorted(sizes.values(), reverse=True) == sorted((c["size"] for c in fixture["output"]["chains"]), reverse=True)

    largest = max(sizes, key=lambda r: sizes[r])
    return {
        "check": "44-transmission-tree",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": not differs and below and consecutive and counts_agree and sizes_agree,
        "criteria": "The same chain and generation for every case, against networkx components and shortest path lengths "
                    "from each root; every case below its infector and each chain on consecutive rows; the same counts",
        "counts": counts,
        "chainSizes": sorted(sizes.values(), reverse=True),
        "largest": {"root": largest, "size": sizes[largest],
                    "generations": max(generation_of[n] for n, r in chain_of.items() if r == largest)},
        "rowsBelowInfector": below, "chainsOnConsecutiveRows": consecutive,
        "differs": differs,
        "notEstablished": [
            "Who infected whom: both sides read the 1861 reconstruction in the infector column.",
            "That the figure is drawn as computed: this checks the computation the figure is drawn from.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "networkx": networkx.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
