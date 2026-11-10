"""Check 45: Fieldwork's lines between records on Map, for Hagelloch, 1861, against pandas.

Fieldwork experiment 200, step 4, draws who infected whom on the map: Map, with a line to the record named in
`infector`, found by `case_ID`, draws a line from each infector's house to the case's, and counts every record under
one outcome. The fixture is that computation run through Fieldwork's own code.

**Independent.** Here the cases are merged with themselves in pandas, infector to case_ID, and each pair's two
locations compared. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **The same lines**: the same set of (infector, case) pairs drawn, and no other.
2. **The same counts** for every outcome: drawn, at one place, naming nothing, naming a case the table does not hold,
   naming itself, naming an id held twice, and with an end that has no location.
3. **Every record counted once**: the outcomes add up to the records.

What this cannot establish: who infected whom, or where each house stood. Both sides read the 1861 reconstruction in
the infector column and this project's georeference of the houses.

Design record: fieldwork/docs/experiments/200-operational-epidemiology.md
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
FIXTURE = HERE.parent / "fixtures" / "links-hagelloch-001.json"
RESULT = HERE.parent / "results" / "check-45-map-links.json"

OUTCOMES = ["drawn", "sameLocation", "noValue", "notFound", "self", "ambiguous", "unlocated"]


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    cases = pandas.DataFrame(fixture["input"]["cases"])
    cases["case_ID"] = cases["case_ID"].astype(str).str.strip()
    cases["infector"] = cases["infector"].fillna("").astype(str).str.strip()
    held = cases["case_ID"].value_counts()

    targets = cases[["case_ID", "lon", "lat"]].rename(columns={"case_ID": "infector", "lon": "ilon", "lat": "ilat"})
    pairs = cases.merge(targets, on="infector", how="left")

    def outcome(row) -> str:
        if row["infector"] == "":
            return "noValue"
        count = held.get(row["infector"], 0)
        if count == 0:
            return "notFound"
        if count > 1:
            return "ambiguous"
        if row["infector"] == row["case_ID"]:
            return "self"
        if pandas.isna(row["lon"]) or pandas.isna(row["ilon"]):
            return "unlocated"
        if row["lon"] == row["ilon"] and row["lat"] == row["ilat"]:
            return "sameLocation"
        return "drawn"

    # One row per case: a case naming an id held twice merges twice and is one record.
    per_case = pairs.groupby("case_ID", sort=False).first().reset_index()
    per_case["outcome"] = per_case.apply(outcome, axis=1)
    counts = {k: int((per_case["outcome"] == k).sum()) for k in OUTCOMES}
    mine = {(r.infector, r.case_ID) for r in per_case.itertuples() if r.outcome == "drawn"}

    theirs_lines = {(l["from"], l["to"]) for l in fixture["output"]["links"]}
    theirs = fixture["output"]["counts"]
    counts_agree = all(theirs[k] == v for k, v in counts.items())
    once = sum(theirs[k] for k in OUTCOMES) == theirs["records"] == len(per_case)
    return {
        "check": "45-map-links",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": mine == theirs_lines and counts_agree and once,
        "criteria": "The same set of (infector, case) lines; the same count for every outcome; every record counted once",
        "records": len(per_case),
        "counts": counts,
        "linesOnlyHere": sorted(mine - theirs_lines),
        "linesOnlyInFieldwork": sorted(theirs_lines - mine),
        "countedOnce": once,
        "notEstablished": [
            "Who infected whom: both sides read the 1861 reconstruction in the infector column.",
            "Where each house stood: both sides read this project's georeference.",
            "That the lines are drawn as computed: this checks the computation the figure is drawn from.",
            "The outcomes Hagelloch does not hold: no case names an unknown case, itself, a duplicated id, or an unplaced "
            "house, so those four counts agree at zero only.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pandas": pandas.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
