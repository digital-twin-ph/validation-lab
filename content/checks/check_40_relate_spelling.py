"""Check 40: Fieldwork Relate, allowing for spelling, against pandas, rapidfuzz and jellyfish.

Fieldwork experiment 193 let Relate match names spelled differently: each name folded, words named dropped as whole
words, and a name not equal matched to the one spelled closest at or above a Jaro-Winkler threshold, 0.88 by default,
where no other is within 0.02 of it. Here, Sierra Leone's 2019 measles cases by residential district, as the line
list writes them ("Bo District"), against OCHA COD-AB's district names as the population table writes them ("Bo",
and "Fabala" for Falaba).

**Independent.** The folding is rewritten here from the declared rule with Python's `unicodedata`; the exact matches
are a pandas merge on the folded keys; the spelling scores are rapidfuzz's (C++) with jellyfish's (Rust) beside them;
the related table is a pandas left merge on the match. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **Every folded name** equal to Fieldwork's "compared as", exactly.
2. **Every outcome and match** (exact, spelling, ambiguous, none, and the value matched) equal, with the outcome
   decided from rapidfuzz's score under the declared rule.
3. **Every spelling score** within 1e-9 of rapidfuzz's.
4. **Every row of the related table**: the district brought across equal to pandas' merge, the unmatched under the
   case's label, and the row count unchanged.

Recorded, not asserted: where jellyfish differs from rapidfuzz, and any name whose score lies within 1e-9 of the
threshold, where the two sides' floating point could fall either way.

What this cannot establish: that a spelling match is the same place. "Fabala" is Falaba because COD-AB holds no other
district like it, which a person sees in the preview. Nor that 0.88 suits district names: case 3 shows that, without
District dropped, thirteen of sixteen still match at 0.88 by the shared prefix alone.

Design record: fieldwork/docs/experiments/193-relate-allows-for-spelling.md
"""
from __future__ import annotations

import json
import pathlib
import platform
import sys
import unicodedata
from datetime import datetime, timezone

import pandas
from rapidfuzz.distance import JaroWinkler
import jellyfish
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "relate-spelling-sl-001.json"
RESULT = HERE.parent / "results" / "check-40-relate-spelling.json"
MARGIN = 0.02
TOLERANCE = 1e-9


def fold(value: str) -> str:
    """NFKC, trimmed, lower-cased; every run of characters that are not a letter or a number becomes one space."""
    base = unicodedata.normalize("NFKC", value).strip().lower()
    out, gap = [], False
    for ch in base:
        if unicodedata.category(ch)[0] in "LN":
            if gap and out:
                out.append(" ")
            out.append(ch)
            gap = False
        else:
            gap = True
    return "".join(out).strip()


def key(value: str, drop: list[str]) -> str:
    dropped = {fold(w) for w in drop if fold(w)}
    return " ".join(w for w in fold(value).split(" ") if w and w not in dropped)


def match_names(left: list[str], right: list[str], spelling: dict) -> dict:
    drop, threshold = spelling["dropWords"], spelling["threshold"]
    names = pandas.DataFrame({"name": sorted({v for v in left if v.strip()})})
    names["compared"] = names["name"].map(lambda v: key(v, drop))
    targets = pandas.DataFrame({"value": sorted({v for v in right if v.strip()})})
    targets["compared"] = targets["value"].map(lambda v: key(v, drop))
    targets = targets[targets["compared"] != ""]
    # EXACT: a merge on the folded key. More than one target per key is ambiguous.
    merged = names.merge(targets, on="compared", how="left")
    out = {}
    for name, group in merged.groupby("name", sort=False):
        compared = group["compared"].iloc[0]
        hits = group["value"].dropna().tolist()
        if compared and len(hits) == 1:
            out[name] = {"compared": compared, "outcome": "exact", "value": hits[0], "score": 1.0, "boundary": False}
            continue
        if compared and len(hits) > 1:
            out[name] = {"compared": compared, "outcome": "ambiguous", "value": None, "score": None, "boundary": False}
            continue
        # SPELLING: every target scored, by rapidfuzz, with jellyfish beside it.
        scored = [(t, JaroWinkler.similarity(compared, c) if compared and c else 0.0,
                   jellyfish.jaro_winkler_similarity(compared, c) if compared and c else 0.0)
                  for t, c in zip(targets["value"], targets["compared"])]
        boundary = any(abs(rf - threshold) <= TOLERANCE for _, rf, _ in scored)
        passing = sorted([s for s in scored if s[1] >= threshold], key=lambda s: -s[1])
        if not passing:
            out[name] = {"compared": compared, "outcome": "none", "value": None, "score": None, "boundary": boundary}
            continue
        close = [s for s in passing if s[1] >= passing[0][1] - MARGIN]
        if len(close) > 1:
            out[name] = {"compared": compared, "outcome": "ambiguous", "value": None, "score": None, "boundary": boundary}
        else:
            out[name] = {"compared": compared, "outcome": "spelling", "value": passing[0][0], "score": passing[0][1],
                         "jellyfish": passing[0][2], "boundary": boundary}
    return out


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    left_rows, right_rows = fixture["input"]["left"]["rows"], fixture["input"]["right"]["rows"]
    left_names = [r["key"]["Residential District"] for r in left_rows]
    right_names = [r["key"]["district"] for r in right_rows]
    comparisons = []
    for number, case in enumerate(fixture["output"]["cases"], start=1):
        request = case["request"]
        ours = match_names(left_names, right_names, request["spelling"])
        theirs = {m["name"]: m for m in case["matches"]}
        names = []
        for name in sorted(set(ours) | set(theirs)):
            a, b = ours.get(name), theirs.get(name)
            agrees = bool(a and b) and a["compared"] == b["compared"] and a["outcome"] == b["outcome"] \
                and a["value"] == b["value"] \
                and (a["score"] is None or b["score"] is None or abs(a["score"] - b["score"]) <= TOLERANCE)
            names.append({"name": name, "agrees": agrees,
                          "pandas": a and {k: a[k] for k in ("compared", "outcome", "value", "score")},
                          "fieldwork": b and {k: b[k] for k in ("compared", "outcome", "value", "score")},
                          "jellyfish": a.get("jellyfish") if a else None, "onThreshold": bool(a and a["boundary"])})
        # THE RELATED TABLE: a left merge on the match, the unmatched under the case's label.
        frame = pandas.DataFrame({"name": left_names, "cases": [r["value"] for r in left_rows]})
        frame["match"] = frame["name"].map(lambda n: ours.get(n, {}).get("value"))
        lookup = pandas.DataFrame({"match": sorted(set(right_names))})
        lookup["district"] = lookup["match"]
        related = frame.merge(lookup, on="match", how="left")
        label = case["unmatchedLabel"]
        related["district"] = related["district"].where(related["district"].notna(), label)
        if label is None:
            related = related[related["district"].notna()]
        got = [(r["key"]["Residential District"], r["key"]["district"], r["value"]) for r in case["table"]["rows"]]
        want = list(zip(related["name"], related["district"], related["cases"]))
        rows_agree = sorted(got) == sorted(want) and case["table"]["rowCount"] == len(related)
        counts = pandas.Series([n["fieldwork"]["outcome"] for n in names if n["fieldwork"]]).value_counts().to_dict()
        comparisons.append({"case": number, "note": case["note"], "request": request,
                            "agrees": all(n["agrees"] for n in names) and rows_agree,
                            "rowsAgree": rows_agree, "rows": len(got), "outcomes": counts, "names": names})
    report = {
        "check": "40-relate-spelling",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": all(c["agrees"] for c in comparisons),
        "criteria": "folded names exact; outcome and match equal, decided from rapidfuzz's score under the declared "
                    "rule; spelling scores within 1e-9 of rapidfuzz; every related row equal to a pandas left merge",
        "comparisons": comparisons,
        "jellyfishDiffers": [{"case": c["case"], "name": n["name"], "rapidfuzz": n["pandas"]["score"], "jellyfish": n["jellyfish"]}
                             for c in comparisons for n in c["names"]
                             if n["jellyfish"] is not None and n["pandas"] and abs(n["jellyfish"] - n["pandas"]["score"]) > TOLERANCE],
        "onThreshold": [{"case": c["case"], "name": n["name"]} for c in comparisons for n in c["names"] if n["onThreshold"]],
        "notEstablished": [
            "That a spelling match is the same place: Fabala is Falaba because COD-AB holds no other district like it.",
            "That 0.88 suits district names: without District dropped, most names still pass it on their shared prefix.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pandas": pandas.__version__,
                        "rapidfuzz": __import__("importlib.metadata", fromlist=["version"]).version("rapidfuzz"),
                        "jellyfish": __import__("importlib.metadata", fromlist=["version"]).version("jellyfish"),
                        "pyodide": "pyodide" in sys.modules},
    }
    return report


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
