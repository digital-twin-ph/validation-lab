"""Check 39: Fieldwork Total within groups, with each group's share, against pandas.

Fieldwork experiment 191 added a share to Total within groups: each group's total or count, and beside it its
percentage of the total of the groups that agree on the columns named `within`, or of all of them. Here, check 29's
South London table: 32 sub-districts' population and cholera deaths related to Snow's water-supply categories.

**Independent.** pandas totals each group itself, and divides by a stratum total it computes with
`groupby(within).transform`; it never reads Fieldwork's totals. Rounding is reproduced from the declared rule, not
from Fieldwork's code: the share is value / stratum total * 1000, rounded half up, divided by 10.

Criteria, fixed before running:

1. **Every total and every count** equal to pandas', exactly: they are integers.
2. **Every share** equal to pandas' under the declared rounding, exactly; and each stratum's shares within 0.1 x its
   number of groups of 100, the most one-decimal rounding can move a total.
3. **An empty cell**: the group summing over it is null, and so is every share in its stratum; the other stratum's
   shares are unchanged from case 1.
4. **Each number is named** in the `statistic` column: the value field's name for a total, `% within ...` or
   `% of all` for a share.

Recorded, not asserted: how many shares Python's own `round(x, 1)` would put elsewhere. It rounds half to even, on
the binary value, so a lab that reached for it would report a disagreement that is a difference of rule.

What this cannot establish: that a share is the measure a reader needs. A share of rows is not a rate, and a share of
deaths by company says nothing of the risk without the population beside it, which is why case 1 shares both.

Design record: fieldwork/docs/experiments/191-shares-within-groups.md
"""
from __future__ import annotations

import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone

import numpy
import pandas
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "group-shares-snow-001.json"
RESULT = HERE.parent / "results" / "check-39-group-shares.json"


def share_name(within: list[str]) -> str:
    return f"% within {' and '.join(within)}" if within else "% of all"


def half_up(x: float) -> float:
    """The declared rounding: value / total * 1000, half up to an integer, then / 10."""
    return math.floor(x + 0.5) / 10


def recompute(frame: pandas.DataFrame, request: dict, value_field: str) -> dict:
    by, within = request["by"], request.get("share", {}).get("within", [])
    if request.get("aggregate") == "count":
        totals = frame.groupby(by, sort=False).size().astype(float)
        name = "rows"
    else:
        # A sum over any empty cell is unknown: skipna=False per group.
        totals = frame.groupby(by, sort=False)["value"].apply(lambda s: s.sum(skipna=False))
        name = value_field
    totals = totals.reset_index(name="total")
    if within:
        totals["stratum"] = totals.groupby(within, sort=False)["total"].transform(lambda s: s.sum(skipna=False))
    else:
        totals["stratum"] = totals["total"].sum(skipna=False)
    raw = totals["total"] / totals["stratum"] * 1000
    totals["share"] = [None if (pandas.isna(r) or s == 0) else half_up(r) for r, s in zip(raw, totals["stratum"])]
    totals["pythonRound"] = [None if pandas.isna(r) else round(t / s * 100, 1) for r, t, s in zip(raw, totals["total"], totals["stratum"])]
    # pandas holds a missing share as NaN in a float column; the comparison is with null, so it is converted here.
    known = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
    out = {}
    for _, row in totals.iterrows():
        key = tuple(str(row[c]) for c in by)
        out[key + (name,)] = known(row["total"])
        out[key + (share_name(within),)] = known(row["share"])
        out[("python",) + key] = known(row["pythonRound"])
    return out


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    table = fixture["input"]["table"]
    frame = pandas.DataFrame([{**r["key"], "value": r["value"]} for r in table["rows"]])
    frame["value"] = pandas.to_numeric(frame["value"])
    comparisons = []
    for i, case in enumerate(fixture["output"]["cases"]):
        f = frame.copy()
        if case["emptied"]:
            hit = numpy.logical_and.reduce([f[k] == v for k, v in case["emptied"]["key"].items()])
            f.loc[hit, "value"] = numpy.nan
        request = case["request"]
        theirs = recompute(f, request, table["valueField"])
        by = request["by"]
        fieldwork = {tuple(r["key"][c] for c in by) + (r["key"]["statistic"],): r["value"] for r in case["table"]["rows"]}
        mine = {k: v for k, v in theirs.items() if k[0] != "python"}
        cells = [{"key": list(k), "pandas": mine.get(k), "fieldwork": fieldwork.get(k),
                  "agrees": k in fieldwork and mine.get(k) == fieldwork.get(k)} for k in mine]
        named = set(fieldwork) == set(mine)
        within = request.get("share", {}).get("within", [])
        name = share_name(within)
        strata: dict = {}
        for k, v in mine.items():
            if k[-1] == name and v is not None:
                s = tuple(k[by.index(w)] for w in within)
                strata.setdefault(s, []).append(v)
        sums = {" · ".join(s) or "all": {"total": round(sum(v), 1), "groups": len(v),
                                          "within": abs(sum(v) - 100) <= 0.1 * len(v) + 1e-9} for s, v in strata.items()}
        python_differs = [{"key": list(k[1:]), "halfUp": mine[k[1:] + (name,)], "pythonRound": v}
                          for k, v in theirs.items() if k[0] == "python" and v != mine[k[1:] + (name,)]]
        comparisons.append({"case": i + 1, "note": case["note"], "request": request, "emptied": case["emptied"],
                            "cells": cells, "everyNumberNamed": named, "strataTotals": sums,
                            "pythonRoundWouldDiffer": python_differs,
                            "agrees": named and all(c["agrees"] for c in cells) and all(s["within"] for s in sums.values())})
    # Criterion 3: with the cell emptied, the deaths' shares are case 1's.
    one, three = comparisons[0], comparisons[2]
    deaths = [c for c in three["cells"] if "death" in " ".join(c["key"]).lower() and c["key"][-1].startswith("%")]
    unchanged = all(any(o["key"] == d["key"] and o["pandas"] == d["pandas"] for o in one["cells"]) for d in deaths)
    unknown = [c for c in three["cells"] if "population" in " ".join(c["key"]).lower() and c["key"][-1].startswith("%")]
    return {
        "check": "39-group-shares",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {"runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
                        "isPyodide": sys.platform == "emscripten", "pandas": pandas.__version__, "numpy": numpy.__version__},
        "fixture": {"id": fixture["fixtureId"], "sha256": digest, "application": fixture["application"],
                    "operation": fixture["operation"]},
        "criterion": {"totals": "every total and count exactly equal", "shares": "every share exactly equal under the "
                      "declared half-up rounding; each stratum within 0.1 x its groups of 100",
                      "empty": "the emptied group and every share in its stratum null; the other stratum unchanged",
                      "named": "each number named in the statistic column"},
        "comparisons": comparisons,
        "emptyCell": {"deathSharesUnchanged": unchanged and bool(deaths),
                      "populationSharesUnknown": bool(unknown) and all(c["pandas"] is None and c["fieldwork"] is None for c in unknown)},
        "notEstablished": [
            "That a share is the measure a reader needs: a share of rows is not a rate, and a share of deaths by company "
            "says nothing of risk without the population beside it.",
            "That one decimal place is enough: a stratum can total 99.9 or 100.1, which the check allows and does not judge.",
        ],
        "agrees": all(c["agrees"] for c in comparisons) and unchanged and bool(deaths)
        and bool(unknown) and all(c["pandas"] is None and c["fieldwork"] is None for c in unknown),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} case {c['case']}: {c['note']}")
        for cell in c["cells"]:
            print(f"     {'OK ' if cell['agrees'] else 'DIFF'} {' · '.join(cell['key'])}: {cell['pandas']} / {cell['fieldwork']}")
        print(f"     strata: {c['strataTotals']}; Python round() would differ on {len(c['pythonRoundWouldDiffer'])}")
    print("empty cell:", result["emptyCell"])
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
