"""Check 22: Fieldwork Cases by period against pandas.

Snow 1855 Table 1 -- deaths by date, 43 daily rows -- binned by day, by week and by month. This
is the epidemic curve the John Snow example renders.

**Genuinely independent.** Fieldwork bins with its own calendar arithmetic; pandas bins with
`resample`, which is a different implementation of a different design. Neither shares code with
the other, unlike the H3 check next door where both sides call the same C library.

Three periods are checked because they are three different calendar rules, and the **week** is
the one most likely to be wrong. Fieldwork keys a week by the Monday of its ISO week; the pandas
equivalent is `resample("W-MON", label="left", closed="left")` -- weeks closed on Monday and
labelled by that Monday.

**The first version of this check had that mapping wrong**, which is worth recording because
the docstring had already named the week as the dangerous case. It used `W-SUN`, whose left
label is the preceding **Sunday**, and every week key came out one day early while every count
stayed entirely plausible: 7 bins, a total of 616, a peak in the right week. Only comparing the
keys caught it. Predicting a hazard did not prevent walking into it.

`W-MON` with the default `label="right"` would have been wrong the other way, labelling each
week by the *following* Monday, so the mapping is spelled out here rather than left implicit in
a frequency string.

Five comparisons per period, criteria fixed before running:

1. **Every bin key**, in order, exactly.
2. **Every count**, exactly. Counts are weighted by the deaths column, not row counts.
3. **The total**, exactly.
4. **Empty periods present**: every period between the first and the last appears, including
   those with no deaths. A curve with gaps omitted misreads as continuous.
5. **The dated and undated record counts**, which is how the widget accounts for anything it
   could not parse.

What this cannot establish: that these dates are right, or that a curve by date of death says
what a reader will take it to say. Snow's table records deaths by the date of death; the
outbreak's shape by date of onset would be shifted earlier by the illness's course, and the
widget carries the declared kind precisely so a chart cannot quietly relabel it.

Design record: fieldwork/docs/experiments/98-the-coverage-ratchet.md
"""
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import pandas as pd

# Fieldwork keys a week by the Monday of its ISO week: in pandas, closed on Monday and labelled
# by that Monday. W-SUN's left label is the preceding Sunday (one day early) and W-MON's default
# right label is the following Monday (seven days late). Both produce plausible counts.
RESAMPLE = {"day": "D", "week": "W-MON", "month": "MS"}
ROOT = Path(__file__).resolve().parent.parent


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    weight_field = declared["weightField"]

    rows = fixture["input"]["rows"]
    frame = pd.DataFrame({
        "date": pd.to_datetime([row["date"] for row in rows], format="%Y-%m-%d", errors="coerce"),
        "weight": [row[weight_field] for row in rows],
    })
    undated = int(frame["date"].isna().sum())
    dated = frame.dropna(subset=["date"]).set_index("date")

    periods = []
    for period, rule in RESAMPLE.items():
        if period == "week":
            binned = dated["weight"].resample(rule, label="left", closed="left").sum()
        else:
            binned = dated["weight"].resample(rule).sum()
        reference = [(stamp.strftime("%Y-%m" if period == "month" else "%Y-%m-%d"), float(value))
                     for stamp, value in binned.items()]

        reported = fixture["output"][period]
        reported_bins = [(b["key"], float(b["count"])) for b in reported["bins"]]
        keys_agree = [k for k, _ in reported_bins] == [k for k, _ in reference]
        counts_agree = all(abs(a - b) < 1e-9 for (_, a), (_, b) in zip(reported_bins, reference)) \
            if keys_agree else False
        total_agrees = abs(reported["total"] - float(binned.sum())) < 1e-9
        # Every period between the first and the last, including the empty ones.
        no_gaps = len(reported_bins) == len(reference)
        empty_bins = sum(1 for _k, count in reference if count == 0)
        accounting_agrees = (reported["undatedRecords"] == undated
                             and reported["datedRecords"] == len(dated))

        periods.append({
            "period": period,
            "resampleRule": rule + (", label=left, closed=left" if period == "week" else ""),
            "binsFieldwork": len(reported_bins),
            "binsReference": len(reference),
            "emptyBins": empty_bins,
            "keysAgree": keys_agree,
            "countsAgree": counts_agree,
            "totalFieldwork": reported["total"],
            "totalReference": float(binned.sum()),
            "totalAgrees": total_agrees,
            "noGaps": no_gaps,
            "accountingAgrees": accounting_agrees,
            "firstKey": reported_bins[0][0] if reported_bins else None,
            "lastKey": reported_bins[-1][0] if reported_bins else None,
            "peak": max(reported_bins, key=lambda row: row[1]) if reported_bins else None,
            "agrees": bool(keys_agree and counts_agree and total_agrees and no_gaps
                           and accounting_agrees),
        })

    return {
        "check": "22-case-series",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "pandas": pd.__version__,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredKeyRule": declared["keyRule"],
            "dateKind": declared["dateKind"],
        },
        "criterion": (
            "per period: every bin key in order exactly, every weighted count exactly, the total exactly, "
            "every period between the first and last present including empty ones, and the dated and undated "
            "record counts exact"
        ),
        "rows": len(rows),
        "datedRows": len(dated),
        "undatedRows": undated,
        "periods": periods,
        "notEstablished": (
            "That a curve by date of death says what a reader will take it to say. Snow's table records deaths "
            "by the date of death; the outbreak's shape by date of onset would be shifted earlier by the course "
            "of the illness. The widget carries the declared kind so a chart cannot relabel it, and no check "
            "can supply the onset dates nobody recorded."
        ),
        "agrees": all(period["agrees"] for period in periods),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "case-series-soho-001.json")
    out = ROOT / "results" / "check-22-case-series.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 22: agrees={result['agrees']} over {result['rows']} rows "
          f"({result['datedRows']} dated, {result['undatedRows']} undated) "
          f"-> {out.relative_to(ROOT.parent)}")
    for period in result["periods"]:
        print(f"  by {period['period']:<6} {period['binsReference']:>3} bins "
              f"({period['emptyBins']} empty), total {period['totalReference']:.0f}, "
              f"{period['firstKey']} to {period['lastKey']}, peak {period['peak']}")
