"""Check 31: Fieldwork Join a table to the study area against a pandas merge.

Snow's Table VIII gives each of 32 sub-districts a population and a death count. The study area
carries 33 named parts, because Streatham is two polygons. Joining the first onto the second is
the choropleth the South London example argues for in prose, and it is the step that turns a table
of rates into a map of rates.

**What is independently checkable here is not the normalisation.** `normaliseName` is Fieldwork's
own, and a check that reimplemented it would be this author's arithmetic checking this author's
arithmetic -- the trap check 27's record names and refused. So three separable things are
recomputed, and the check says which is which:

1. **The merge, given keys.** `pandas.DataFrame.merge` joins the rate table onto the parts on the
   folded key the fixture carries, left on the parts so every part survives. Fully independent:
   which part takes which value, how many matched, which carry null, and the two Streatham parts
   taking one value between them.
2. **The raw-string baseline.** Equality on the unfolded names needs no normalisation at all, so
   it is independent in the strongest sense available. 23 of 32 rows match; the other 9 differ
   only by a comma, and one by a doubled space.
3. **What the folding is allowed to do**, as a property rather than a reimplementation. For every
   part, the folded key must equal the name reduced by deleting every non-alphanumeric character
   and lowercasing. That is weaker than an independent folding and it is not nothing: it refuses a
   folding that expanded `St.` to `Saint`, dropped a word, folded two distinct names together, or
   touched a letter.

**And a negative control, because the data cannot supply one.** Snow's table and these boundaries
have no pair that differs by more than punctuation, so nothing in the example tests a name that
OUGHT not to match -- 32 of 32 is also the score of a rule that matched too readily. The fixture
renames one part to `Camberwell Green`, a real place the table does not carry, and the join must
report it unmatched rather than find it a home.

`rapidfuzz` and `jellyfish` are carried on that case alone, in the role the score interval plays
in check 27: never asserted, only reported. They say how close `Camberwell Green` is to
`Camberwell`, which is how close a similarity-based linkage would have come to accepting it. This
widget is a keyed join and has no threshold and no review band, and the number is what that
decision is worth.

Criteria, fixed before running:

1. **Every part's value** equal to a pandas left merge on the folded key, compared part by part
   including the nulls, with the Streatham pair carrying one value and flagged `shared`.
2. **The counts** -- parts, rows, matched parts, matched rows, unmatched, shared -- all equal.
3. **The raw baseline**: 23 of 32 rows match on unfolded equality, and the 9 that do not are
   exactly the 9 the fixture reports, each differing from its row only by non-alphanumerics.
4. **The folding touched nothing else**: every folded key equals its name's alphanumeric
   reduction, and no two distinct names fold together.
5. **The negative control** is reported unmatched, with `unmatched-boundary` naming it, and the
   other 32 parts unchanged from criterion 1.

What this cannot establish: **that folding punctuation is the right rule for names.** It is right
for these two files, where every difference is a comma. A boundary file spelling `St Mary` against
a table's `Saint Mary`, or `Newington Trinity` against `Trinity, Newington`, would fail this join
and should -- but whether failing is the right behaviour there is a judgement about the data, and
the practitioner declares a synonym or fixes the source. Nothing here speaks to it.

Nor that the 33 parts are the right geography. Streatham being two polygons is a fact about the
digitisation; both take the same rate, which is correct for a rate and would be wrong for a count.

Design record: fieldwork/src/area-join.ts, and experiment 142 for the chain it sits in.
"""
from __future__ import annotations

import json
import pathlib
import platform
import re
import sys
from datetime import datetime, timezone

import pandas
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "area-join-snow-001.json"
RESULT = HERE.parent / "results" / "check-31-area-join.json"

# The reduction criterion 4 compares against: delete everything that is not a letter or a digit.
# Deliberately NOT Fieldwork's folding -- that one collapses runs to a single space and keeps
# word boundaries. Two strings equal under this reduction differ only in non-alphanumerics, which
# is exactly the claim being checked and is weaker than reimplementing the fold.
_reduce = lambda name: re.sub(r"[^0-9a-z]+", "", str(name).lower())


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    """The report, so a notebook and a headless run read the same numbers."""
    fixture, digest = load_fixture(fixture_path)
    params = fixture["declaredParameters"]
    rows = fixture["input"]["table"]["rows"]
    cases = fixture["output"]["cases"]
    comparisons = []
    divergences = []

    fuzzy, exact, control = cases[0], cases[1], cases[2]

    # ---- Criterion 4 first, because criteria 1 and 2 merge on these keys and the checks below
    # are only worth as much as the keys are. Checked on the FUZZY case, which is the one the
    # example runs.
    fold_problems = []
    seen: dict[str, str] = {}
    for part in fuzzy["parts"]:
        if _reduce(part["key"]) != _reduce(part["name"]):
            fold_problems.append(
                {"name": part["name"], "key": part["key"],
                 "why": "the folded key is not the name's alphanumeric reduction"})
        held = seen.get(part["key"])
        if held is not None and _reduce(held) != _reduce(part["name"]):
            fold_problems.append(
                {"name": part["name"], "key": part["key"],
                 "why": f"folds together with {held!r}, which is a different name"})
        seen.setdefault(part["key"], part["name"])
    folding = {"partsChecked": len(fuzzy["parts"]), "problems": fold_problems,
               "agrees": not fold_problems,
               "criterion": "every folded key equals its name with all non-alphanumerics deleted "
                            "and lowercased, and no two distinct names share a folded key"}
    if fold_problems:
        divergences.append({"note": "the folding touched more than non-alphanumerics",
                            "problems": fold_problems})

    # ---- Criteria 1 and 2, on each of the three cases. The merge is pandas'; the folded keys for
    # the parts come from the fixture, and the table's keys are folded the same way the case
    # declares, which for `exact` means not folded at all.
    for case in (fuzzy, exact, control):
        folded = {p["index"]: p["key"] for p in case["parts"]}
        parts = pandas.DataFrame([{"index": p["index"], "name": p["name"], "key": folded[p["index"]]}
                                  for p in case["parts"]])
        # The table side is keyed by the SAME rule the case declares, taken from how Fieldwork
        # keyed the parts: for `fuzzy`, a part's key is its folded name, so a row's key is its
        # folded group. Reduced identically on both sides so the merge is comparing like with like
        # without this check owning the fold.
        if case["normalisation"] == "fuzzy":
            table = pandas.DataFrame([{"key": _reduce(r["key"]["group"]), "value": r["value"]}
                                      for r in rows])
            parts["key"] = parts["key"].map(_reduce)
        else:
            table = pandas.DataFrame([{"key": str(r["key"]["group"]).strip().lower(),
                                       "value": r["value"]} for r in rows])
            parts["key"] = parts["key"].map(lambda k: str(k).strip().lower())

        # A key appearing twice in the table would multiply rows; it does not here, and asserting
        # it keeps the merge honest rather than assuming it.
        duplicate_table_keys = int(table["key"].duplicated().sum())
        merged = parts.merge(table, on="key", how="left")

        expected = [(None if pandas.isna(v) else float(v)) for v in merged["value"]]
        reported = [p["value"] for p in case["parts"]]
        matched_parts = int(merged["value"].notna().sum())
        matched_rows = int(table[table["key"].isin(set(parts["key"]))].shape[0])
        # A part sharing its key with another part: both take the one value.
        shared = set(parts["key"][parts["key"].duplicated(keep=False)])
        shared_parts = int(parts["key"].isin(shared).sum()) if shared else 0

        checks = {
            "valuesMatch": expected == reported,
            "partCount": case["counts"]["parts"] == len(parts),
            "rowCount": case["counts"]["rows"] == len(table),
            "matchedParts": case["counts"]["matchedParts"] == matched_parts,
            "matchedRows": case["counts"]["matchedRows"] == matched_rows,
            "unmatchedParts": case["counts"]["unmatchedParts"] == len(parts) - matched_parts,
            "sharedParts": case["counts"]["sharedParts"] == shared_parts,
            "noDuplicateTableKeys": duplicate_table_keys == 0,
            "sharedFlagged": sorted(p["name"] for p in case["parts"] if p["shared"])
                             == sorted(parts["name"][parts["key"].isin(shared)]),
        }
        agrees = all(checks.values())
        if not agrees:
            divergences.append({
                "note": case["note"], "failed": [k for k, v in checks.items() if not v],
                "fieldwork": case["counts"],
                "pandas": {"parts": len(parts), "rows": len(table), "matchedParts": matched_parts,
                           "matchedRows": matched_rows, "sharedParts": shared_parts}})
        comparisons.append({
            "note": case["note"],
            "normalisation": case["normalisation"],
            "fieldwork": case["counts"],
            "pandas": {"parts": len(parts), "rows": len(table), "matchedParts": matched_parts,
                       "matchedRows": matched_rows,
                       "unmatchedParts": len(parts) - matched_parts, "sharedParts": shared_parts},
            "unmatchedPartNames": [p["name"] for p in case["parts"] if not p["matched"]],
            "diagnosticCodes": sorted({d["code"] for d in case["diagnostics"]}),
            "checks": checks,
            "agrees": agrees,
        })

    # ---- Criterion 3: what the folding bought, and that each pair it joined differs only in
    # non-alphanumerics.
    raw_unmatched = [p for p in exact["parts"] if not p["matched"]]
    table_keys = [r["key"]["group"] for r in rows]
    pairs = []
    for part in raw_unmatched:
        row = next((k for k in table_keys if _reduce(k) == _reduce(part["name"])), None)
        pairs.append({"boundary": part["name"], "row": row,
                      "equalOnceReduced": row is not None,
                      "differsOnlyInPunctuation": row is not None
                                                  and _reduce(row) == _reduce(part["name"])
                                                  and row != part["name"]})
    folding_gain = {
        "rawMatchedRows": exact["counts"]["matchedRows"],
        "foldedMatchedRows": fuzzy["counts"]["matchedRows"],
        "rowsTheFoldingWon": fuzzy["counts"]["matchedRows"] - exact["counts"]["matchedRows"],
        "shareOfRows": round((fuzzy["counts"]["matchedRows"] - exact["counts"]["matchedRows"])
                             / fuzzy["counts"]["rows"], 4),
        "pairs": pairs,
        "agrees": all(p["differsOnlyInPunctuation"] for p in pairs),
        "note": "A join on the raw strings would have left these unmatched and drawn a choropleth "
                "missing them -- every one of them a sub-district whose name carries a comma in "
                "the table and not in the boundary file.",
    }
    if not folding_gain["agrees"]:
        divergences.append({"note": "a folded pair differs by more than non-alphanumerics",
                            "pairs": [p for p in pairs if not p["differsOnlyInPunctuation"]]})

    # ---- The negative control, with two similarity measures reported beside it.
    renamed_to = control["renamedTo"]
    renamed_from = control["renamedFrom"]
    control_unmatched = [p["name"] for p in control["parts"] if not p["matched"]]
    similarity = {}
    try:
        from rapidfuzz.distance import JaroWinkler
        similarity["rapidfuzzJaroWinkler"] = round(
            JaroWinkler.similarity(renamed_to.lower(), renamed_from.lower()), 6)
    except Exception as error:  # noqa: BLE001 - reported, never fatal
        similarity["rapidfuzzJaroWinkler"] = f"unavailable: {type(error).__name__}"
    try:
        import jellyfish
        similarity["jellyfishJaroWinkler"] = round(
            jellyfish.jaro_winkler_similarity(renamed_to.lower(), renamed_from.lower()), 6)
    except Exception as error:  # noqa: BLE001
        similarity["jellyfishJaroWinkler"] = f"unavailable: {type(error).__name__}"

    control_checks = {
        "reportedUnmatched": control_unmatched == [renamed_to],
        "diagnosticNamesIt": any(d["code"] == "unmatched-boundary" and renamed_to in d["subject"]
                                 for d in control["diagnostics"]),
        "othersUnchanged": [p["value"] for p in control["parts"] if p["name"] != renamed_to]
                           == [p["value"] for p in fuzzy["parts"]
                               if p["name"] != renamed_from],
    }
    if not all(control_checks.values()):
        divergences.append({"note": control["note"],
                            "failed": [k for k, v in control_checks.items() if not v]})

    result = {
        "check": "31-area-join",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"CPython {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pandas.__version__,
        },
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"],
                    "boundaryProvenance": fixture.get("boundaryProvenance")},
        "criterion": {
            "values": "every part's value equal to a pandas left merge on the folded key, nulls included",
            "counts": "parts, rows, matched parts, matched rows, unmatched and shared all equal",
            "raw": "23 of 32 rows match on unfolded equality, and the 9 that do not differ from their row only in non-alphanumerics",
            "folding": "every folded key equals its name's alphanumeric reduction, and no two distinct names fold together",
            "control": "a part renamed to a place the table does not carry is reported unmatched and named, with the other 32 unchanged",
        },
        "declaredParameters": params,
        "folding": folding,
        "foldingGain": folding_gain,
        "comparisons": comparisons,
        "negativeControl": {
            "note": control["note"],
            "constructed": control.get("constructed"),
            "renamedFrom": renamed_from,
            "renamedTo": renamed_to,
            "unmatched": control_unmatched,
            "similarityToTheNameItReplaced": similarity,
            "whatTheRefusalIsWorth": (
                f"{renamed_to!r} and {renamed_from!r} are close enough that a similarity-based "
                "linkage would plausibly accept them -- the Jaro-Winkler figures above say how "
                "close. This widget has no threshold and no review band, so it reports the part "
                "unmatched and draws it empty. The graded machinery exists in deduplicate_points "
                "and is deliberately not reached for here."),
            "checks": control_checks,
            "agrees": all(control_checks.values()),
        },
        "divergences": divergences,
        "notEstablished": [
            "That folding punctuation is the right rule for names. It is right for these two "
            "files, where every difference is a comma or a doubled space. A boundary spelling "
            "'St Mary' against a table's 'Saint Mary' would fail this join, and whether failing "
            "is right there is a judgement about the data rather than an outcome of this check.",
            "That the folding itself is correctly implemented. It is not independently "
            "reimplemented here, on purpose: a second copy written by the same author is not a "
            "second opinion. What is checked is a property it must satisfy -- that it changed "
            "nothing but non-alphanumerics and folded no two distinct names together.",
            "That the 33 parts are the right geography. Streatham being two polygons is a fact "
            "about the digitisation. Both parts take the same rate, which is correct for a rate "
            "and would be wrong for a count.",
            "That a sub-district rate measures an exposure. In the middle 16 sub-districts both "
            "companies supplied the same streets, so the rate there mixes two exposures -- Snow's "
            "own confounding, and why he went house to house.",
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
              f"{c['fieldwork']['matchedParts']:>2}/{c['fieldwork']['parts']} parts, "
              f"{c['fieldwork']['matchedRows']:>2}/{c['fieldwork']['rows']} rows  {c['note']}")
    g = result["foldingGain"]
    print(f"{'OK ' if g['agrees'] else 'DIFF'} the folding won {g['rowsTheFoldingWon']} rows "
          f"({g['shareOfRows']:.0%} of the table), all differing only in punctuation")
    f = result["folding"]
    print(f"{'OK ' if f['agrees'] else 'DIFF'} the folding touched nothing else "
          f"({f['partsChecked']} parts checked)")
    n = result["negativeControl"]
    print(f"{'OK ' if n['agrees'] else 'DIFF'} {n['renamedTo']!r} reported unmatched; "
          f"Jaro-Winkler to {n['renamedFrom']!r} "
          f"{n['similarityToTheNameItReplaced'].get('rapidfuzzJaroWinkler')}")
    print("AGREES" if result["agrees"] else "DIVERGES")
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
