"""Check 43: Fieldwork's serial intervals and secondary cases in Hagelloch, 1861, against pandas.

Fieldwork experiment 200 built who infected whom by hand on the 188 measles cases: the cases related to themselves on
`infector` for each infector's prodrome date, one date taken from the other for the serial interval, and the cases
counted by `infector` and related back on `case_ID` for the secondary cases, the children nobody names kept as 0, a
number the practitioner typed. The fixture is that chain run through Fieldwork's own functions.

**Independent.** Here the same three columns go through pandas: a self-merge on infector = case_ID, the difference of
two `pandas.to_datetime` columns in days, and `value_counts` of `infector` reindexed over every case_ID with 0 for a
case nobody names. Nothing of Fieldwork's code is read.

Criteria, fixed before running:

1. **Every serial interval** equal, in whole days; a case with no infector has none on either side.
2. **Every count of secondary cases** equal, and so their sum and the number of zeros.

What this cannot establish: who infected whom. The infector column is a reconstruction, made from the 1861 record of
the outbreak; both sides read the same reconstruction. Nor is the mean of the secondary cases an estimate of R.

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
FIXTURE = HERE.parent / "fixtures" / "chains-hagelloch-001.json"
RESULT = HERE.parent / "results" / "check-43-hagelloch-chains.json"


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    cases = pandas.DataFrame(fixture["input"]["cases"]).astype(str)
    cases["prodrome"] = pandas.to_datetime(cases["date_of_prodrome"], format="%Y-%m-%d")

    infectors = cases[["case_ID", "prodrome"]].rename(columns={"case_ID": "infector", "prodrome": "infector_prodrome"})
    merged = cases.merge(infectors, on="infector", how="left", validate="many_to_one")
    merged["serial"] = (merged["prodrome"] - merged["infector_prodrome"]).dt.days
    serial = {row.case_ID: (None if pandas.isna(row.serial) else int(row.serial)) for row in merged.itertuples()}

    named = cases.loc[cases["infector"] != "", "infector"].value_counts()
    secondary = named.reindex(cases["case_ID"], fill_value=0).astype(int).to_dict()

    differs = []
    for c in fixture["output"]["cases"]:
        problems = []
        if c["serialIntervalDays"] != serial[c["case_ID"]]:
            problems.append(f"serial {c['serialIntervalDays']} != {serial[c['case_ID']]}")
        if c["secondaryCases"] != secondary[c["case_ID"]]:
            problems.append(f"secondary {c['secondaryCases']} != {secondary[c['case_ID']]}")
        if problems:
            differs.append({"case_ID": c["case_ID"], "problems": problems})

    intervals = sorted(v for v in serial.values() if v is not None)
    counts = list(secondary.values())
    distribution = pandas.Series(counts).value_counts().sort_index()
    return {
        "check": "43-hagelloch-chains",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "agrees": not differs and len(fixture["output"]["cases"]) == len(cases),
        "criteria": "Every serial interval equal in whole days, none where no infector is recorded; every count of "
                    "secondary cases equal, a case nobody names 0",
        "cases": len(cases),
        "serialIntervals": {"n": len(intervals), "median": float(pandas.Series(intervals).median()),
                            "min": intervals[0], "max": intervals[-1]},
        "secondaryCases": {"sum": sum(counts), "zeros": counts.count(0), "max": max(counts),
                           "distribution": {str(k): int(v) for k, v in distribution.items()}},
        "differs": differs,
        "notEstablished": [
            "Who infected whom: the infector column is a reconstruction from the 1861 record, read alike by both sides.",
            "That the mean of the secondary cases estimates R.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pandas": pandas.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
