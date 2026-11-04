"""Check 32: Fieldwork Select rows by value, as a range, against pandas `Series.between`.

The range came from the NYC smoke workflow, where fourteen days out of 3,653 were fourteen ticks
(Fieldwork experiment 171). The fixture is London's daily deaths 2002 to 2006, read from the
published Stata file by Fieldwork's own reader, so the dates are the ones the file declares.

**Genuinely independent.** `Series.between(left, right, inclusive='both')` is pandas' own
implementation of the same question, and what a practitioner would otherwise write. Here the column
is parsed by pandas, as dates or as numbers, rather than compared as Fieldwork compares it.

**The case worth the check is the numbers.** A range compared as text keeps `100` inside 60 to 90,
because "1" sorts before "6". Ozone from 60 to 90 is a range of numbers with values on both sides
of every digit boundary the file holds.

Criteria, fixed before running:

1. **Each case keeps exactly the rows pandas keeps**, the same dates in the same order, and the kept
   and dropped counts add to the table.
2. **An open end** is a one-sided comparison, `>=` alone.
3. **An emptied cell is outside the range**: pandas' NaN is never `between`, and Fieldwork drops the
   row too, one fewer than case 2.

What this cannot establish: that a range was the right selection. A period chosen to show a peak is
still a choice; the receipt records it without judging it.

Design record: fieldwork/docs/experiments/171-a-range-of-values.md
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
FIXTURE = HERE.parent / "fixtures" / "select-range-london-001.json"
RESULT = HERE.parent / "results" / "check-32-select-range.json"


def _frame(table: dict) -> pandas.DataFrame:
    return pandas.DataFrame([{**row["key"], "value": row["value"]} for row in table["rows"]])


def _parsed(series: pandas.Series, column: str) -> pandas.Series:
    """The column as pandas reads it: dates for `date`, numbers otherwise. An empty cell is NaN/NaT."""
    if column == "date":
        return pandas.to_datetime(series.replace("", None), format="%Y-%m-%d")
    return pandas.to_numeric(series.replace("", None))


def _bound(value: str, column: str):
    if value == "":
        return None
    return pandas.Timestamp(value) if column == "date" else float(value)


def _kept(frame: pandas.DataFrame, case: dict) -> list[str]:
    column = case["keyColumn"]
    values = _parsed(frame[column], column)
    low, high = _bound(case["from"], column), _bound(case["to"], column)
    if low is not None and high is not None:
        mask = values.between(low, high, inclusive="both")
    elif low is not None:
        mask = values >= low
    else:
        mask = values <= high
    return frame.loc[mask.fillna(False), "date"].tolist()


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    table = fixture["input"]["table"]
    base = _frame(table)
    comparisons, divergences = [], []

    for case in fixture["output"]["cases"]:
        frame = base.copy()
        if case["emptied"]:
            mask = frame["date"] == case["emptied"]["date"]
            if int(mask.sum()) != 1:
                raise SystemExit(f"The emptied date selects {int(mask.sum())} rows here, not 1; re-export the fixture.")
            frame.loc[mask, case["keyColumn"]] = ""
        expected = _kept(frame, case)
        checks = {
            "sameRowsSameOrder": case["dates"] == expected,
            "keptCount": case["kept"] == len(expected),
            "countsAddUp": case["kept"] + case["dropped"] == len(frame),
        }
        if not all(checks.values()):
            only_fw = sorted(set(case["dates"]) - set(expected))[:10]
            only_pd = sorted(set(expected) - set(case["dates"]))[:10]
            divergences.append({"note": case["note"], "failed": [k for k, v in checks.items() if not v],
                                "onlyFieldwork": only_fw, "onlyPandas": only_pd})
        comparisons.append({"note": case["note"], "keyColumn": case["keyColumn"],
                            "from": case["from"], "to": case["to"], "emptied": case["emptied"],
                            "fieldwork": case["kept"], "pandas": len(expected),
                            "first": expected[0] if expected else None, "last": expected[-1] if expected else None,
                            "checks": checks, "agrees": all(checks.values())})

    # The text comparison a range must not be, recorded so the size of that mistake is visible.
    numbers = next(c for c in fixture["output"]["cases"] if c["keyColumn"] == "ozone" and not c["emptied"])
    as_text = int(((base["ozone"] >= numbers["from"]) & (base["ozone"] <= numbers["to"])).sum())

    return {
        "check": "32-select-range",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pandas.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "rows": "the same dates in the same order as Series.between(inclusive='both') on the column parsed by pandas",
            "openEnd": "a one-sided comparison",
            "emptyCell": "outside every range, as NaN is never between",
        },
        "comparisons": comparisons,
        "divergences": divergences,
        "ozoneComparedAsText": {"kept": as_text, "insteadOf": numbers["kept"],
                                "note": "What 60 to 90 keeps if ozone is compared as text. Not what either implementation does."},
        "notEstablished": [
            "That a range was the right selection. A period chosen to show a peak is still a choice, and the "
            "receipt records it without judging it.",
            "Datetime columns. The fixture's dates carry no time, and a To given as a date excludes times later "
            "that day.",
        ],
        "agrees": bool(not divergences),
    }


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        print(f"{'OK ' if c['agrees'] else 'DIFF'} {c['fieldwork']:>5} / {c['pandas']:<5} {c['note']}")
    text = result["ozoneComparedAsText"]
    print(f"     ozone 60 to 90 compared as text would keep {text['kept']}, not {text['insteadOf']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
