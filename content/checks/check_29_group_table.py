"""Check 29: Fieldwork Total a table within groups against a pandas groupby.

The six numbers the South London contingency table is made of: 32 sub-districts' populations and
cholera deaths, totalled within the three water-supply categories Snow's Table XII declares.
Until 2026-10-26 those six were computed by hand and inlined into the worked example. They are
now computed by the application, which is why they are worth recomputing by somebody else.

**Genuinely independent.** `pandas.DataFrame.groupby(...).sum()` is a separate implementation by
separate authors of the same operation, and it is what a practitioner would otherwise use. The
sums are arithmetic and should agree exactly -- integers, no approximation, so the tolerance is
zero rather than small.

**The case worth the check is the one where they are MEANT to disagree.** Every long table in
Fieldwork can hold an empty cell. Summing over one silently returns a total that is too small by
an unknown amount: a stratum whose population nobody recorded coming out smaller rather than
coming out unknown. Fieldwork returns nothing known for that group and names it; pandas, by
default, returns the sum of the cells that were present.

**And pandas has no option for Fieldwork's rule**, which this check found by reaching for the
obvious one and watching it not work. `min_count=1` reads as "at least one value required" and is
the first thing anyone writes here. It bounds how many values must be PRESENT, not whether any are
ABSENT, so on a group holding eleven numbers and one empty cell it returns the eleven -- the
default's answer, from the option named for missing data. Written down because the next author
will reach for it too.

Four expressions are therefore recorded, and only one of them is the comparison:

| Expression | On the emptied group | What it is |
| --- | --- | --- |
| `sum()` | 147,945 | the default. Short by one sub-district, and nothing says so |
| `sum(min_count=1)` | 147,945 | the trap. Reads like the rule, behaves like the default |
| `sum(min_count=12)` | nothing known | right here, wrong in general: it also nulls every group with fewer than twelve rows |
| `sum(skipna=False)` per group | nothing known | **the comparison.** Nothing known exactly where a cell was empty, and the group size does not enter it |

A check that compared only against the default would report a disagreement and call it a defect.
One that compared only against `min_count=1` would have reported a disagreement and called it a
defect too, for a different and more embarrassing reason.

Criteria, fixed before running:

1. **All six totals** equal to `groupby(['water_supply','measure']).sum()`, exactly.
2. **The group count and the collapse**: 6 groups from 64 rows, and `sub_district` reported as
   the dropped column.
3. **With one cell emptied**: that group's total is null, equal to a per-group
   `sum(skipna=False)`, and the other five are unchanged from criterion 1.
4. **The gap is named** with the right counts -- how many rows were summed and how many were
   empty -- so a practitioner can find the cell.
5. **The size of the disagreement with the default** is recorded in people, together with what
   `min_count=1` returns. Neither is asserted equal: both are recorded, because the first is what
   the decision costs and the second is what it is mistaken for.

What this cannot establish: **that summing is the right operation for these columns.** It is
right for counts and wrong for rates -- deaths per 1,000 in three sub-districts do not add to
deaths per 3,000 in one -- and nothing in the data tells either implementation which it has.
Fieldwork offers sum and nothing else for that reason, and leaves `MEANS` unbuilt rather than
offering a choice it cannot police. The protection is the absence of the other option, which no
check can verify.

Nor that nothing known is the right answer rather than the honest one. It is a refusal to guess,
and a practitioner who needs a number still has to go and find the missing cell.

Design record: fieldwork/docs/experiments/142-an-epi-kernel-exercised.md
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
FIXTURE = HERE.parent / "fixtures" / "group-snow-001.json"
RESULT = HERE.parent / "results" / "check-29-group-table.json"


def _frame(table: dict) -> pandas.DataFrame:
    rows = [{**row["key"], "value": row["value"]} for row in table["rows"]]
    return pandas.DataFrame(rows)


def _as_dict(grouped) -> dict:
    """Totals as {(group key tuple): value or None}, so two implementations are comparable."""
    return {tuple(str(part) for part in (key if isinstance(key, tuple) else (key,))):
            (None if pandas.isna(value) else int(value))
            for key, value in grouped.items()}


def _totals(frame: pandas.DataFrame, by: list[str], min_count: int = 0) -> dict:
    """pandas' sum, with its own missing-value option."""
    return _as_dict(frame.groupby(by, sort=False)["value"].sum(min_count=min_count))


def _totals_all_or_nothing(frame: pandas.DataFrame, by: list[str]) -> dict:
    """The rule Fieldwork states, expressed in pandas: a group holding any empty cell is unknown.

    `Series.sum(skipna=False)` is pandas' own behaviour for exactly this, applied per group. It is
    NOT `min_count`, which counts the values present rather than noticing the ones absent, and it
    does not depend on how many rows a group happens to have.
    """
    return _as_dict(frame.groupby(by, sort=False)["value"].apply(lambda s: s.sum(skipna=False)))


def _reported(case: dict, by: list[str]) -> dict:
    return {tuple(str(row["key"][column]) for column in by): row["value"]
            for row in case["table"]["rows"]}


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    by = fixture["declaredParameters"]["by"]
    table = fixture["input"]["table"]
    base = _frame(table)
    cases = fixture["output"]["cases"]

    comparisons = []
    divergences = []

    # --- Case 1: the six totals, over the table as it stands.
    whole = cases[0]
    pandas_totals = _totals(base, by, min_count=0)
    reported = _reported(whole, by)
    checks = {
        "totalsMatch": reported == pandas_totals,
        "groupCount": whole["groups"] == len(pandas_totals),
        "collapsedFrom": whole["collapsedFrom"] == len(base),
        "droppedColumn": sorted(whole["dropped"]) == sorted(c for c in table["keys"] if c not in by),
        "noGaps": whole["gaps"] == [],
    }
    if not all(checks.values()):
        divergences.append({"note": whole["note"], "failed": [k for k, v in checks.items() if not v],
                            "fieldwork": {str(k): v for k, v in reported.items()},
                            "pandas": {str(k): v for k, v in pandas_totals.items()}})
    comparisons.append({
        "note": whole["note"],
        "rowsIn": len(base), "groupsOut": whole["groups"], "dropped": whole["dropped"],
        "totals": [{"group": list(key), "fieldwork": reported.get(key), "pandas": value,
                    "agrees": reported.get(key) == value}
                   for key, value in pandas_totals.items()],
        "checks": checks,
        "agrees": all(checks.values()),
    })

    # --- Case 2: one cell emptied. The fixture names which, so the same cell is emptied here.
    holed_case = cases[1]
    emptied = holed_case["emptied"]
    mask = pandas.Series(True, index=base.index)
    for column, value in emptied["key"].items():
        mask &= base[column] == value
    # The fixture empties exactly one row, so this must select exactly one.
    if int(mask.sum()) != 1:
        raise SystemExit(f"The emptied key selects {int(mask.sum())} rows here, not 1. "
                         "The fixture and this check disagree about the input; re-export it.")
    holed = base.copy()
    holed.loc[mask, "value"] = float("nan")

    strict = _totals_all_or_nothing(holed, by)   # the rule Fieldwork states
    default = _totals(holed, by)                 # the behaviour Fieldwork refuses
    min_count_1 = _totals(holed, by, min_count=1)  # the option that reads like the rule
    # Right on this group only because it happens to hold twelve rows; it would null any group
    # with fewer. Recorded to show that the group size is what makes it work, not the rule.
    group_size_threshold = _totals(holed, by, min_count=12)
    reported_holed = _reported(holed_case, by)
    group_key = tuple(str(emptied["key"][column]) for column in by)

    others_unchanged = all(reported_holed[key] == pandas_totals[key]
                           for key in pandas_totals if key != group_key)
    # How many input rows that group holds, counted here from the input rather than taken from
    # the report: the gap has to account for every one of them, one empty and the rest summed.
    in_group = pandas.Series(True, index=base.index)
    for column, value in zip(by, group_key):
        in_group &= base[column].astype(str) == value
    group_rows = int(in_group.sum())
    gaps = holed_case["gaps"]
    holed_checks = {
        "matchesAllOrNothing": reported_holed == strict,
        "thatGroupIsNull": reported_holed[group_key] is None,
        "othersUnchanged": others_unchanged,
        "groupCount": holed_case["groups"] == len(strict),
        # One group reported, and it is the one whose cell was emptied.
        "oneGapNamed": len(gaps) == 1 and gaps[0]["group"] == " · ".join(group_key),
        # Every row of that group accounted for: exactly one empty, the rest summed.
        "gapCounts": (len(gaps) == 1
                      and gaps[0]["rowsEmpty"] == 1
                      and gaps[0]["rowsSummed"] == group_rows - 1),
    }
    if not all(holed_checks.values()):
        divergences.append({"note": holed_case["note"],
                            "failed": [k for k, v in holed_checks.items() if not v],
                            "fieldwork": {str(k): v for k, v in reported_holed.items()},
                            "pandas_skipna_false": {str(k): v for k, v in strict.items()}})

    hidden = default[group_key]
    comparisons.append({
        "note": holed_case["note"],
        "emptied": emptied,
        "group": list(group_key),
        "fieldwork": reported_holed[group_key],
        "pandasSkipnaFalse": strict[group_key],
        "pandasDefault": hidden,
        "pandasMinCount1": min_count_1[group_key],
        "pandasMinCountGroupSize": group_size_threshold[group_key],
        "whyNotMinCount": (
            "min_count bounds how many values must be PRESENT, not whether any are ABSENT, so "
            f"min_count=1 returns {min_count_1[group_key]} -- the default's answer -- on a group "
            "holding eleven numbers and one empty cell. min_count=12 does return nothing known "
            "here, and only because this group has twelve rows: it would null every smaller "
            "group too. sum(skipna=False) per group is the rule itself, and the group size does "
            "not enter it."),
        "whatTheDefaultWouldHide": {
            "total": hidden,
            "insteadOf": emptied["wasValue"] + hidden,
            "shortBy": emptied["wasValue"],
            "unit": table["valueField"],
            "note": ("A default sum reports that number as the group's population. It is short by "
                     "the one cell nobody recorded, and no total in the result says so."),
        },
        "gaps": holed_case["gaps"],
        "checks": holed_checks,
        "agrees": all(holed_checks.values()),
    })

    result = {
        "check": "29-group-table",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pandas.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "totals": "exactly equal to groupby(by).sum(); these are integer counts and nothing is approximated",
            "shape": "6 groups from 64 rows, with sub_district reported as the dropped column",
            "emptyCell": "that group null, equal to a per-group sum(skipna=False), with the other five unchanged",
            "gap": "the group named, with the rows summed and the rows empty adding to its row count",
            "default": "the size of the disagreement with sum() recorded in people, with what min_count=1 returns beside it; neither asserted equal",
        },
        "comparisons": comparisons,
        "divergences": divergences,
        "notEstablished": [
            "That summing is right for these columns. It is right for counts and wrong for rates, "
            "and neither implementation can tell which it has been given. Fieldwork offers sum "
            "and nothing else for that reason; the protection is the absence of the other "
            "option, which no check can verify.",
            "That nothing known is the right answer rather than the honest one. It refuses to "
            "guess; a practitioner who needs the number still has to find the missing cell.",
            "That the three supply categories are the right strata. The both-companies group is "
            "300,149 of 486,936 people, and what to do with it is the practitioner's judgement.",
        ],
        "agrees": bool(not divergences),
    }
    return result


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    whole = result["comparisons"][0]
    for total in whole["totals"]:
        print(f"{'OK ' if total['agrees'] else 'DIFF'} {total['pandas']:>7}  {' · '.join(total['group'])}")
    holed = result["comparisons"][1]
    hidden = holed["whatTheDefaultWouldHide"]
    print(f"{'OK ' if holed['agrees'] else 'DIFF'} one cell emptied: "
          f"Fieldwork {holed['fieldwork']}, skipna=False {holed['pandasSkipnaFalse']}  |  "
          f"default {holed['pandasDefault']}, min_count=1 {holed['pandasMinCount1']} "
          f"-- short by {hidden['shortBy']} {hidden['unit']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
