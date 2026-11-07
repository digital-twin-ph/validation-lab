"""Check 36: Fieldwork's lag-response plot, Append rows and Chart, against pandas `concat` and `pivot`.

Five Poisson models of dengue cases on land surface temperature 0, 2, 4, 6 and 8 weeks earlier (Fieldwork experiment
180) are stacked by Append rows, each row labelled with its lag, declared a number in weeks; Select rows keeps the
temperature term; Chart draws each lag's rate ratio as a point with its 95% interval as a whisker, on a log scale with
a dashed line at 1 (experiment 181). The fixture holds the five Regression tables, the stacked table, and the points,
scale and line the chart specification draws.

**Independent where it matters.** pandas rebuilds the stack with `concat(keys=...)`, keeps the term with a boolean
mask and gathers the estimate and its limits with `pivot`: the same question answered by other code. Which statistic
is the estimate and which are its limits is read from the interval the fixture's input declares, as Fieldwork reads it.

Criteria, fixed before running:

1. **The stack is the same table**: every row, in order, with the same lag label, term, statistic and value.
2. **Each point is the regression's numbers exactly**: the estimate and both limits at each lag, no tolerance, since
   nothing is computed between them.
3. **The lags are placed as numbers**, on a quantitative axis, at 0, 2, 4, 6 and 8.
4. **The scale is logarithmic and its domain holds every limit and 1**, and the line is drawn at 1.

What this cannot establish: that a lag-response plot is the right figure, or that any lag has an effect. The five
points come from five separate models, and the intervals allow nothing for correlation from week to week (experiment
180). Nor does it check the drawn pixels: it checks the specification the renderer is given.

Design record: fieldwork/docs/experiments/181-lag-response-figure.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import pandas
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "lag-response-brazil-001.json"
RESULT = HERE.parent / "results" / "check-36-lag-response.json"


def _frame(table: dict) -> pandas.DataFrame:
    return pandas.DataFrame([{**row["key"], "value": row["value"]} for row in table["rows"]])


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    params = fixture["declaredParameters"]
    append, select = params["append"], params["select"]
    interval = fixture["input"]["interval"]
    output = fixture["output"]

    # 1. THE STACK, by pandas: concat with the labels as keys, in port order.
    frames = [_frame(t) for t in fixture["input"]["tables"]]
    column = append["sourceColumn"]
    stacked = (pandas.concat(frames, keys=append["labels"], names=[column])
               .reset_index(level=column).reset_index(drop=True))
    stacked = stacked[[*fixture["input"]["tables"][0]["keys"], column, "value"]]
    fieldwork_stack = _frame(output["stacked"])[[*fixture["input"]["tables"][0]["keys"], column, "value"]]
    same_stack = stacked.astype(str).equals(fieldwork_stack.astype(str))

    # 2. THE POINTS, by pandas: keep the term, pivot the statistics, lag as a number.
    kept = stacked[stacked[select["keyColumn"]].isin(select["values"])]
    wide = kept.pivot(index=column, columns=interval["column"], values="value")
    wide.index = pandas.to_numeric(wide.index)
    wide = wide.sort_index()
    expected = [{"at": int(at) if float(at).is_integer() else float(at), "estimate": float(r[interval["estimate"]]),
                 "lower": float(r[interval["lower"]]), "upper": float(r[interval["upper"]])} for at, r in wide.iterrows()]
    drawn = sorted(output["points"], key=lambda p: p["at"])
    points = [{"at": e["at"], "pandas": e, "fieldwork": d, "agrees": e == d} for e, d in zip(expected, drawn)]
    same_points = len(expected) == len(drawn) and all(p["agrees"] for p in points)

    # 3 and 4. THE AXES, from the declaration: numeric lags, a log scale holding every limit and 1, the line at 1.
    values = [v for e in expected for v in (e["estimate"], e["lower"], e["upper"])]
    low, high = output["yDomain"]
    checks = {
        "sameStack": bool(same_stack),
        "samePoints": bool(same_points),
        "lagsAsNumbers": output["xType"] == "quantitative" and output["stacked"]["numericKeys"] == {column: append["labelsAreNumbers"]["unit"]},
        "logScale": output["yScale"] == ("log" if interval["ratio"] else "linear"),
        "domainHoldsLimitsAndOne": low < min(values + [1]) and high > max(values + [1]),
        "lineAtOne": output["referenceLine"] == 1,
    }
    divergences = [name for name, ok in checks.items() if not ok]

    return {
        "check": "36-lag-response",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pandas.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest, "application": fixture["application"],
                    "operation": fixture["operation"], "alsoExercises": fixture.get("alsoExercises", [])},
        "criterion": {
            "stack": "every row in order equal to pandas.concat(frames, keys=labels)",
            "points": "estimate and both limits at each lag equal to the pivot, no tolerance",
            "axes": "lags on a quantitative axis; a log scale for a ratio whose domain holds every limit and 1; a line at 1",
        },
        "rows": {"fieldwork": output["stacked"]["rowCount"], "pandas": len(stacked)},
        "points": points,
        "checks": checks,
        "divergences": divergences,
        "notEstablished": [
            "That a lag-response plot is the right figure, or that any lag has an effect: each point is its own model, "
            "and the intervals allow nothing for correlation from week to week.",
            "The drawn pixels. This checks the specification the renderer is given, not what Vega-Lite drew.",
        ],
        "agrees": not divergences,
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"rows: Fieldwork {result['rows']['fieldwork']}, pandas {result['rows']['pandas']}")
    for p in result["points"]:
        f = p["fieldwork"]
        print(f"{'OK ' if p['agrees'] else 'DIFF'} lag {p['at']}: {f['estimate']} ({f['lower']} to {f['upper']})")
    for name, ok in result["checks"].items():
        print(f"{'OK ' if ok else 'DIFF'} {name}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
