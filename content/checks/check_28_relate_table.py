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

**Rebuilt 2026-10-28 for relate_table 0.3.0**, which changed the subject in three ways: keys are
compared with punctuation and case folded by default, a key the right table does not carry now
REFUSES until the practitioner declares what to do with it, and the retained share of each numeric
variable is part of the result. The previous fixture declared "no case folding, no punctuation
folding", which is no longer true of the widget, and the export that builds it broke outright on the
withheld-key case. The folding is reimplemented here from its declared rule and never imported --
borrowing it would compare the widget with itself.

**And the case this check recorded that it could not reach is now reachable.** It said: *"St.
George, Camberwell" against "St George Camberwell" is the case a practitioner will actually meet,
and neither this fixture nor this check reaches it.* The published sub-district boundary is a second
source for the same 32 names and spells nine of them without their comma, so the fixture now carries
the same two tables compared both ways: 23 of 32 matched exactly, 32 of 32 folded. One knob,
eighteen rows, and two different retained shares.

Criteria, fixed before running:

1. **Every produced row** matches a left merge on the FOLDED key: the same keys, each with the
   same brought category and the same value. Compared as a set of records, not row by row, so a
   difference in ordering is not reported as a disagreement.
0. **The declared folding, reimplemented**: NFKC, trim, lowercase; and for `fuzzy`, every run of
   characters that are neither letters nor digits becomes a single space, then trim.
2. **The row count is unchanged.** 64 in, 64 out. A relate that multiplied rows would be a
   merge, and the widget says it is not one.
3. **The distinct categories that landed**, in first-seen order, against the order a merge
   produces from the same input.
4. **The withheld-key case**: the same rows dropped as a merge drops, and the gap reported by
   name with the right count.
5. **The ambiguous key is refused.** The message must name the key and both values. Recorded
   beside it: how many rows a merge returns for the same input, which is what the refusal buys.
6. **An undeclared gap is refused.** Where a key does not match and the practitioner has said
   nothing, the widget refuses; a merge proceeds and leaves NaN, and no total reveals it.
7. **The retained share of each variable**, summed independently, and the identity that follows:
   a rate of one variable over another computed on the matched rows equals its value over every
   offered row multiplied by the ratio of their retained shares.

What this cannot establish: **that folding is the right matching.** The check shows what each
setting does to two published spellings of the same 32 sub-districts. It does not show that nine
names differing by a comma are nine names of the same place -- that is a judgement about the
sources, and a fold that joined two genuinely different places would be wrong in exactly the way
this check cannot see.

Nor **that the practitioner's declaration is the right one**: the check confirms that `drop` and
`keep` produce the totals each claims, and which a study should use is not a question a merge can
answer.

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

import unicodedata

import pandas
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "relate-snow-001.json"
RESULT = HERE.parent / "results" / "check-28-relate-table.json"


def _frame(table: dict) -> pandas.DataFrame:
    """A long table as a frame: one column per key, plus the value."""
    rows = [{**row["key"], "value": row["value"]} for row in table["rows"]]
    return pandas.DataFrame(rows)


def _fold(value: object, mode: str) -> str:
    """The declared comparison, REIMPLEMENTED from `declaredParameters.matching`.

    Not imported from Fieldwork, and not a call into it: the folding is the thing under check, so
    a check that borrowed the implementation would compare it with itself. The declared rule is
    NFKC, trim, lowercase; and for `fuzzy`, replace every run of characters that are neither
    letters nor digits with a single space, then trim. `str.isalnum` is Python's own answer to
    "letter or digit", arrived at separately from Fieldwork's `\\p{L}\\p{N}`.
    """
    base = unicodedata.normalize("NFKC", str(value)).strip().lower()
    if mode != "fuzzy":
        return base
    out: list[str] = []
    separated = False
    for ch in base:
        if ch.isalnum():
            out.append(ch)
            separated = False
        elif not separated:
            out.append(" ")
            separated = True
    return "".join(out).strip()


def _records(frame: pandas.DataFrame, columns: list[str]) -> list[dict]:
    """Comparable records, ordered so that a difference in row order is not a disagreement."""
    ordered = frame[columns + ["value"]]
    return sorted(
        ({**{c: row[c] for c in columns}, "value": (None if pandas.isna(row["value"]) else row["value"])}
         for _, row in ordered.iterrows()),
        key=lambda r: tuple(str(r[c]) for c in columns),
    )


def _right_frame(fixture: dict, case: dict, on: str, bring: str) -> pandas.DataFrame:
    """The right table this case joins against, assembled from the fixture's named inputs."""
    rows = [dict(r["key"]) for r in fixture["input"][case["rightInput"]]["rows"]]
    withheld = case.get("withheldKey")
    if withheld is not None:
        rows = [r for r in rows if r[on] != withheld]
    if case.get("ambiguousValues"):
        rows = rows + [{on: case["ambiguousKey"], bring: case["ambiguousValues"][1]}]
    return pandas.DataFrame([{on: r[on], bring: r[bring]} for r in rows])


def _shares(left: pandas.DataFrame, matched: pandas.DataFrame, measure: str) -> dict:
    """Each variable's total before and after, and the fraction retained — independently."""
    offered = left.groupby(measure)["value"].sum()
    related = matched.groupby(measure)["value"].sum() if len(matched) else offered * 0
    out = {}
    for name, total in offered.items():
        got = float(related.get(name, 0.0))
        out[str(name)] = {"all": float(total), "related": got,
                          "share": (got / float(total)) if float(total) else None}
    return out


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    params = fixture["declaredParameters"]
    on, measure = params["on"], params["measureKey"]

    left = _frame(fixture["input"]["left"])
    comparisons = []
    refusals = []
    divergences = []

    for case in fixture["output"]["cases"]:
        request = case["request"]
        bring = request["bring"]
        mode = request.get("normalisation", "fuzzy")
        declared = (request.get("unmatched") or {}).get("decision")
        label = (request.get("unmatched") or {}).get("label")
        right = _right_frame(fixture, case, on, bring)

        folded_left = left.assign(_k=[_fold(v, mode) for v in left[on]])
        folded_right = right.assign(_k=[_fold(v, mode) for v in right[on]])

        # AMBIGUITY IS CHECKED AGAINST THE FOLDED KEY, because the folding can create it.
        per_key = folded_right.groupby("_k")[bring].nunique()
        ambiguous_keys = sorted(per_key[per_key > 1].index.tolist())

        if case["refused"]:
            # Fieldwork refused. The merge is run anyway, to record what it does instead — which
            # is the whole reason a refusal case is in the fixture.
            merged = folded_left.merge(folded_right, on="_k", how="left", suffixes=("", "_r"))
            if case.get("ambiguousValues"):
                checks = {
                    "refused": True,
                    "namesTheKey": case["ambiguousKey"] in case["refused"],
                    "namesBothValues": all(v in case["refused"] for v in case["ambiguousValues"]),
                    "returnedNoTable": case["table"] is None,
                    "pandasMultipliedRows": len(merged) > len(left),
                    "weFoundItAmbiguousToo": bool(ambiguous_keys),
                }
                instead = (f"A merge returns {len(merged)} rows where the left table has {len(left)}: "
                           f"the rows for that key each match twice, so both companies appear in the "
                           f"stratification carrying the same population, and no total reveals it.")
            else:
                unmatched = merged[merged[bring].isna()]
                checks = {
                    "refused": True,
                    "namesTheKey": (case.get("withheldKey") or "") in case["refused"],
                    "returnedNoTable": case["table"] is None,
                    "pandasProceeded": True,
                    "weFoundAGapToo": len(unmatched) > 0,
                }
                instead = (f"A merge proceeds and returns {len(merged)} rows with {len(unmatched)} "
                           f"of them carrying NaN in {bring}. Nothing asks what should happen to "
                           f"them, and a total over the result is a total over a table the "
                           f"practitioner never chose.")
            agrees = all(checks.values())
            if not agrees:
                divergences.append({"note": case["note"],
                                    "failed": [k for k, v in checks.items() if not v]})
            refusals.append({"note": case["note"], "constructed": case.get("constructed"),
                             "fieldworkRefused": case["refused"], "whatAMergeDoesInstead": instead,
                             "pandasRowCount": int(len(merged)), "checks": checks, "agrees": agrees})
            continue

        merged = folded_left.merge(folded_right, on="_k", how="left", suffixes=("", "_r"))
        matched = merged[merged[bring].notna()]
        gap_rows = merged[merged[bring].isna()]

        if declared == "keep":
            carried = merged.copy()
            carried[bring] = carried[bring].fillna(label)
            produced = carried
            expected_related, expected_dropped, expected_kept = len(matched), 0, len(gap_rows)
        else:
            produced = matched
            expected_related, expected_dropped, expected_kept = len(matched), len(gap_rows), 0

        columns = case["table"]["keys"]
        expected = _records(produced, columns)
        reported = sorted(
            ({**row["key"], "value": row["value"]} for row in case["table"]["rows"]),
            key=lambda r: tuple(str(r[c]) for c in columns),
        )
        pandas_values = list(dict.fromkeys(matched[bring].tolist()))
        if declared == "keep" and label not in pandas_values:
            pandas_values = pandas_values + [label]
        pandas_gaps = sorted(
            ({"key": key, "rows": int(count)} for key, count in gap_rows[on].value_counts().items()),
            key=lambda g: g["key"],
        )
        fieldwork_gaps = sorted(case["gaps"], key=lambda g: g["key"])
        our_shares = _shares(left, matched, measure)
        their_shares = {s["measure"]: s for s in case["shares"]}

        def share_agrees(name: str) -> bool:
            mine, theirs = our_shares[name], their_shares.get(name)
            if theirs is None:
                return False
            if mine["share"] is None or theirs["share"] is None:
                return mine["share"] == theirs["share"]
            return (abs(mine["all"] - theirs["all"]) < 1e-9
                    and abs(mine["related"] - theirs["related"]) < 1e-9
                    and abs(mine["share"] - theirs["share"]) < 1e-9)

        checks = {
            "rowsMatch": expected == reported,
            "rowCount": case["table"]["rowCount"] == len(produced),
            "relatedCount": case["related"] == expected_related,
            "droppedCount": case["dropped"] == expected_dropped,
            "keptCount": case.get("kept", 0) == expected_kept,
            "valuesInOrder": case["values"] == pandas_values,
            "gapsNamed": fieldwork_gaps == pandas_gaps,
            "matchedKeyCount": case["overlap"]["matched"] == int(matched["_k"].nunique()),
            "sharesAgree": all(share_agrees(n) for n in our_shares),
            "noAmbiguityHere": not ambiguous_keys,
        }
        agrees = all(checks.values())
        if not agrees:
            divergences.append({"note": case["note"],
                                "failed": [k for k, v in checks.items() if not v],
                                "fieldwork": {"rowCount": case["table"]["rowCount"],
                                              "related": case["related"], "dropped": case["dropped"],
                                              "kept": case.get("kept"), "gaps": fieldwork_gaps,
                                              "shares": case["shares"]},
                                "pandas": {"rowCount": int(len(produced)),
                                           "related": int(expected_related),
                                           "dropped": int(expected_dropped),
                                           "kept": int(expected_kept), "gaps": pandas_gaps,
                                           "shares": our_shares}})
        comparisons.append({
            "note": case["note"],
            "comparison": mode, "bring": bring, "decision": declared,
            "leftRows": int(len(left)), "rightRows": int(len(right)),
            "fieldwork": {"rowCount": case["table"]["rowCount"], "related": case["related"],
                          "dropped": case["dropped"], "kept": case.get("kept"),
                          "gaps": fieldwork_gaps, "values": case["values"],
                          "matchedKeys": case["overlap"]["matched"], "shares": case["shares"]},
            "pandas": {"rowCount": int(len(produced)), "related": int(expected_related),
                       "dropped": int(expected_dropped), "kept": int(expected_kept),
                       "gaps": pandas_gaps, "values": pandas_values,
                       "matchedKeys": int(matched["_k"].nunique()), "shares": our_shares},
            "checks": checks,
            "agrees": agrees,
        })

    # THE IDENTITY WORTH RECOMPUTING, independently and on the pair of cases that differ only in
    # the comparison. Fieldwork states that an inner join multiplies a rate of one variable over
    # another by exactly the ratio of their retained shares. Here that is deaths over population
    # across the boundary-spelling pair: the rate is computed from the frames, and the multiplier
    # from the shares, and the two have to meet.
    identity = None
    strict = next((c for c in comparisons if c["bring"] == "supplier" and c["comparison"] == "exact"), None)
    if strict is not None:
        shares = strict["pandas"]["shares"]
        if "deaths_seven_weeks" in shares and "population_1851" in shares:
            deaths, people = shares["deaths_seven_weeks"], shares["population_1851"]
            rate_all = deaths["all"] / people["all"] * 1000
            rate_matched = deaths["related"] / people["related"] * 1000
            multiplier = deaths["share"] / people["share"]
            identity = {
                "claim": "rate over the matched rows = rate over every offered row x share(numerator)/share(denominator)",
                "ratePerThousandAllRows": rate_all,
                "ratePerThousandMatchedRows": rate_matched,
                "multiplierFromShares": multiplier,
                "ratePerThousandPredicted": rate_all * multiplier,
                "holds": abs(rate_all * multiplier - rate_matched) < 1e-9,
                "reading": ("The two variables do not fall in step, so excluding the unmatched rows "
                            "moves the estimate and not only its precision."),
            }
            if not identity["holds"]:
                divergences.append({"note": "the share identity", "failed": ["holds"],
                                    "fieldwork": {"claimed": "exact"}, "pandas": identity})

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
            "rows": "every produced row identical to a pandas left merge on the FOLDED key, compared as an ordered set of records",
            "folding": "the declared comparison reimplemented here from its stated rule, never imported",
            "rowCount": "unchanged by relating, except where the practitioner declared that unmatched rows be kept",
            "values": "the distinct brought categories, in first-seen order",
            "gaps": "the same rows unmatched as a merge leaves NaN, and each key named with its count",
            "shares": "each variable's offered total, matched total and retained fraction, summed independently",
            "identity": "a rate of one variable over another over the matched rows equals its value over all rows times the ratio of their retained shares",
            "ambiguous": "refused, with the key and both values named; a merge multiplies rows instead",
            "undeclaredGap": "refused; a merge proceeds and leaves NaN, which no total reveals",
        },
        "comparisons": comparisons,
        "refusals": refusals,
        "shareIdentity": identity,
        "divergences": divergences,
        "notEstablished": [
            "That folding is the right comparison. It is now the default, and this check shows "
            "what each setting does on two published spellings of the same 32 sub-districts -- "
            "not that nine names differing by a comma are nine names of the same place. That is "
            "a judgement about the sources, and a fold that joined two genuinely different "
            "places would be wrong in exactly the way this check cannot see.",
            "That relating is right for bringing MEASURES across. That adds rows rather than a "
            "column and is deliberately not built, so nothing here speaks to it.",
            "That the category is the right stratifier. Snow's third group -- sub-districts "
            "supplied by both companies -- is 300,149 of the 486,936 people in the table, and "
            "what to do with it is the practitioner's judgement, not an outcome of the join.",
            "That the practitioner's declaration is the right one. The check confirms that drop "
            "and keep produce the totals each claims; which of them a study should use is not a "
            "question a merge can answer.",
        ],
        "agrees": bool(not divergences),
    }
    return result


def main() -> int:
    result = run()
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["comparisons"]:
        flags = "".join("." if v else "X" for v in c["checks"].values())
        print(f"{'OK ' if c['agrees'] else 'DIFF'} [{flags}] {c['comparison']:5s} "
              f"{c['fieldwork']['matchedKeys']:>2} keys, {c['fieldwork']['rowCount']:>2} rows, "
              f"{c['fieldwork']['dropped']} dropped, {c['fieldwork']['kept']} kept  {c['note'][:58]}")
    for r in result["refusals"]:
        flags = "".join("." if v else "X" for v in r["checks"].values())
        print(f"{'OK ' if r['agrees'] else 'DIFF'} [{flags}] refused; a merge returns "
              f"{r['pandasRowCount']} rows  {r['note'][:58]}")
    i = result["shareIdentity"]
    if i:
        print(f"{'OK ' if i['holds'] else 'DIFF'} identity: {i['ratePerThousandAllRows']:.3f} x "
              f"{i['multiplierFromShares']:.4f} = {i['ratePerThousandPredicted']:.3f} per 1000 "
              f"(observed {i['ratePerThousandMatchedRows']:.3f})")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
