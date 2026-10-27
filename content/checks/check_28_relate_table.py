"""Check 28: Fieldwork Relate a table against a pandas merge.

Snow's Table XII says which water company supplied each of 32 sub-districts. Table VIII gives
each sub-district's population and its cholera deaths, as 64 rows of a long table. Relating the
first onto the second is what turns two published tables into a table that can be stratified by
supply, and it is the first step of the chain the South London example's contingency table is
built from.

**There is no arithmetic here, and that is the point.** A relate brings a CATEGORY across; no
number is computed. So this check is not about whether two implementations agree on a sum. It is
about the MATCHING, and about one case in particular where the two are meant to disagree.

**Genuinely independent.** `pandas.DataFrame.merge` is a separate implementation by separate
authors of a left join on a key, and it is the operation a practitioner would otherwise reach
for. Where it agrees, the agreement is worth having. Where it does not, the difference is the
finding rather than a defect in either:

- **An ambiguous key.** A right table giving one key two different values is REFUSED by
  Fieldwork, with a message naming the key and both values. A merge MULTIPLIES the rows: 64 rows
  become 66, the stratification is quietly wrong, and nothing reports it. Fieldwork's refusal is
  the behaviour under check, and pandas' row count is the measure of what it prevents.
- **An unmatched key.** Both drop the row. Fieldwork additionally reports it by name and count;
  a merge leaves NaN unless told otherwise. Checked for the same dropped rows AND for the names.

Criteria, fixed before running:

1. **Every related row** matches a left merge exactly: the same 64 keys, each with the same
   brought category and the same value. Compared as a set of records, not row by row, so a
   difference in ordering is not reported as a disagreement.
2. **The row count is unchanged.** 64 in, 64 out. A relate that multiplied rows would be a
   merge, and the widget says it is not one.
3. **The distinct categories that landed**, in first-seen order, against the order a merge
   produces from the same input.
4. **The withheld-key case**: the same rows dropped as a merge drops, and the gap reported by
   name with the right count.
5. **The ambiguous key is refused.** The message must name the key and both values. Recorded
   beside it: how many rows a merge returns for the same input, which is what the refusal buys.

What this cannot establish: **that exact matching is the right matching.** Snow's two tables
spell every sub-district identically, so this data cannot show what happens when they do not --
"St. George, Camberwell" against "St George Camberwell" is the case a practitioner will actually
meet, and neither this fixture nor this check reaches it. Fieldwork folds nothing but surrounding
whitespace, which is a decision recorded in `src/relate-table.ts` and not a result here.

Nor that relating is the right operation for bringing MEASURES across. That adds rows rather than
a column, has a different failure mode, and is deliberately not built.

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
FIXTURE = HERE.parent / "fixtures" / "relate-snow-001.json"
RESULT = HERE.parent / "results" / "check-28-relate-table.json"


def _frame(table: dict) -> pandas.DataFrame:
    """A long table as a frame: one column per key, plus the value."""
    rows = [{**row["key"], "value": row["value"]} for row in table["rows"]]
    return pandas.DataFrame(rows)


def _records(frame: pandas.DataFrame, columns: list[str]) -> list[dict]:
    """Comparable records, ordered so that a difference in row order is not a disagreement."""
    ordered = frame[columns + ["value"]]
    return sorted(
        ({**{c: row[c] for c in columns}, "value": (None if pandas.isna(row["value"]) else row["value"])}
         for _, row in ordered.iterrows()),
        key=lambda r: tuple(str(r[c]) for c in columns),
    )


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    params = fixture["declaredParameters"]
    on, bring = params["on"], params["bring"]

    left = _frame(fixture["input"]["left"])
    right_rows = fixture["input"]["right"]["rows"]
    cases = fixture["output"]["cases"]
    comparisons = []
    divergences = []

    # --- Case 1 and case 2: the relate, and the relate with one key withheld. Both are a left
    # merge of the bring column onto the left table, then dropping what did not match.
    for case in cases[:2]:
        withheld = case.get("withheldKey")
        rows = [r for r in right_rows if withheld is None or r["key"][on] != withheld]
        right = pandas.DataFrame([{on: r["key"][on], bring: r["key"][bring]} for r in rows])

        merged = left.merge(right, on=on, how="left")
        matched = merged[merged[bring].notna()]
        dropped_keys = merged[merged[bring].isna()][on]

        columns = case["table"]["keys"]
        expected = _records(matched, columns)
        reported = sorted(
            ({**row["key"], "value": row["value"]} for row in case["table"]["rows"]),
            key=lambda r: tuple(str(r[c]) for c in columns),
        )
        # First-seen order of the categories, which is what the widget reports and what a
        # practitioner reads before grouping by the column.
        pandas_values = list(dict.fromkeys(matched[bring].tolist()))
        # Gaps as a merge would report them, if asked: each unmatched key and how many rows.
        pandas_gaps = sorted(
            ({"key": key, "rows": int(count)} for key, count in dropped_keys.value_counts().items()),
            key=lambda g: g["key"],
        )
        fieldwork_gaps = sorted(case["gaps"], key=lambda g: g["key"])

        checks = {
            "rowsMatch": expected == reported,
            "rowCountUnchanged": case["table"]["rowCount"] == len(matched),
            "relatedCount": case["related"] == len(matched),
            "droppedCount": case["dropped"] == int(len(dropped_keys)),
            "valuesInOrder": case["values"] == pandas_values,
            "gapsNamed": fieldwork_gaps == pandas_gaps,
        }
        agrees = all(checks.values())
        if not agrees:
            divergences.append({"note": case["note"], "failed": [k for k, v in checks.items() if not v],
                                "fieldwork": {"rowCount": case["table"]["rowCount"],
                                              "dropped": case["dropped"], "gaps": fieldwork_gaps},
                                "pandas": {"rowCount": int(len(matched)),
                                           "dropped": int(len(dropped_keys)), "gaps": pandas_gaps}})
        comparisons.append({
            "note": case["note"],
            "leftRows": int(len(left)),
            "rightRows": int(len(right)),
            "fieldwork": {"rowCount": case["table"]["rowCount"], "related": case["related"],
                          "dropped": case["dropped"], "gaps": fieldwork_gaps, "values": case["values"]},
            "pandas": {"rowCount": int(len(matched)), "dropped": int(len(dropped_keys)),
                       "gaps": pandas_gaps, "values": pandas_values},
            "checks": checks,
            "agrees": agrees,
        })

    # --- Case 3: the ambiguous key. Fieldwork refuses; the merge is run to record what it does
    # instead, which is the whole reason this case is in the fixture.
    ambiguous = cases[2]
    key = ambiguous["ambiguousKey"]
    values = ambiguous["ambiguousValues"]
    rows = [{on: r["key"][on], bring: r["key"][bring]} for r in right_rows]
    rows.append({on: key, bring: values[1]})
    right = pandas.DataFrame(rows)
    multiplied = left.merge(right, on=on, how="left")

    refusal = ambiguous["refused"] or ""
    refusal_checks = {
        "refused": bool(ambiguous["refused"]),
        "namesTheKey": key in refusal,
        "namesBothValues": all(v in refusal for v in values),
        "returnedNoTable": ambiguous["table"] is None,
    }
    refusal_agrees = all(refusal_checks.values())
    if not refusal_agrees:
        divergences.append({"note": ambiguous["note"],
                            "failed": [k for k, v in refusal_checks.items() if not v],
                            "fieldwork": {"refused": ambiguous["refused"]},
                            "pandas": {"rowCount": int(len(multiplied))}})

    result = {
        "check": "28-relate-table",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pandas.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criterion": {
            "rows": "every related row identical to a pandas left merge, compared as an ordered set of records",
            "rowCount": "unchanged by relating: a relate that multiplied rows would be a merge",
            "values": "the distinct brought categories, in first-seen order",
            "gaps": "the same rows dropped as a merge drops, and each unmatched key named with its count",
            "ambiguous": "refused, with the key and both values named; a merge multiplies rows instead",
        },
        "comparisons": comparisons,
        "ambiguousKey": {
            "note": ambiguous["note"],
            "constructed": ambiguous.get("constructed"),
            "key": key,
            "values": values,
            "fieldworkRefused": ambiguous["refused"],
            "pandasRowCount": int(len(multiplied)),
            "pandasRowsForThatKey": int((multiplied[on] == key).sum()),
            "leftRowsForThatKey": int((left[on] == key).sum()),
            "whatTheRefusalBuys": (
                f"A merge returns {len(multiplied)} rows where the left table has {len(left)}, "
                f"because the {int((left[on] == key).sum())} rows for that key each match twice. "
                "Both companies would then appear in the stratification, each carrying the same "
                "population, and no total in the result reveals it."),
            "checks": refusal_checks,
            "agrees": refusal_agrees,
        },
        "divergences": divergences,
        "notEstablished": [
            "That exact matching is the right matching. Snow's two tables spell every "
            "sub-district identically, so this data never exercises a name that differs by "
            "punctuation or case -- the case a practitioner will actually meet. Fieldwork folds "
            "surrounding whitespace and nothing else, by decision rather than by this result.",
            "That relating is right for bringing MEASURES across. That adds rows rather than a "
            "column and is deliberately not built, so nothing here speaks to it.",
            "That the category is the right stratifier. Snow's third group -- sub-districts "
            "supplied by both companies -- is 300,149 of the 486,936 people in the table, and "
            "what to do with it is the practitioner's judgement, not an outcome of the join.",
        ],
        "agrees": bool(not divergences),
    }
    return result


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        flags = "".join("." if v else "X" for v in c["checks"].values())
        print(f"{'OK ' if c['agrees'] else 'DIFF'} [{flags}] "
              f"{c['fieldwork']['rowCount']} rows, {c['fieldwork']['dropped']} dropped  {c['note']}")
    a = result["ambiguousKey"]
    print(f"{'OK ' if a['agrees'] else 'DIFF'} refused; a merge returns {a['pandasRowCount']} rows  {a['note']}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
