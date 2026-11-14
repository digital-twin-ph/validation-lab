"""Check 51: the MERS-CoV example's epidemiology, its workflows 6 to 8, against pandas.

Fieldwork 0.114.0 (2026-11-14). The practitioner: *"For MERS if there are any more epi computations that can be
included let's do that."* Three workflows were added to the example: deaths by age class and by sex in a two-by-two;
the days from exposure to onset and from onset to death, computed by rules, with the median by outcome; and the
secondary cases per source and the median days between onsets by setting. Total within groups gained Mean, Median and
a column to total other than the value column for them, which this check is the first independent test of.

**The data is not in this repository**, as in check 49: the fixture carries Fieldwork's results, the commit and each
file's digest, and the files are read at that commit after their digest is verified.

**Independent.** pandas reads the CSVs, takes calendar differences of the dates, counts and takes medians itself. The
two-by-two's estimates are computed here from the textbook formulas: the risk ratio with Katz's log interval, the odds
ratio with Woolf's (Wald log) interval, the risk difference with the unpooled Wald interval, at the normal quantile from
Python's own `statistics.NormalDist`. Nothing here reads Fieldwork's tables.

Criteria, fixed before running:

1. **Each case's days**, from exposure to onset and from onset to death: exact, empty where a date is.
2. **Every count**: exact.
3. **Every share**: exact under the declared rounding, a count / its stratum's total * 1000, half up, / 10.
4. **Every median**: exact. The middle value of those present, or the mean of the middle two; a group with an empty
   value, not excluded, has none.
5. **The two-by-two**: the four cells exact; each estimate and both limits within 1e-9 relative.

What this cannot establish: that exposure-to-onset days are an incubation period (some are negative, where the
exposure window ran past onset; both sides keep them); that `diff_dt_onset` is a serial interval, which the package
does not document; that a ratio over 162 cases, whose interval holds 1, says anything about sex.
"""
from __future__ import annotations

import io
import json
import math
import pathlib
import platform
import sys
from datetime import datetime, timezone
from statistics import NormalDist

import pandas
from .fixtures import load_fixture
from .check_49_mers import source_bytes

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "mers-epi-001.json"
RESULT = HERE.parent / "results" / "check-51-mers-epi.json"


def days(later: str, earlier: str) -> str:
    if not later or not earlier:
        return ""
    return str(int((pandas.Timestamp(later) - pandas.Timestamp(earlier)).days))


def half_up(count: float, total: float):
    return None if not total else math.floor(count / total * 1000 + 0.5) / 10


def median(values: list[float]):
    s = sorted(values)
    m = len(s) // 2
    return None if not s else s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    theirs = fixture["output"]
    commit = fixture["source"].split(" at ")[1].split(":")[0]
    files = {f["path"]: source_bytes(f, commit) for f in fixture["input"]["files"]}
    read = lambda p: pandas.read_csv(io.BytesIO(files[p]), dtype=str, keep_default_na=False).apply(lambda c: c.str.strip())
    cases, links = read("data/mers_korea_2015_linelist.csv"), read("data/mers_korea_2015_contacts.csv")
    differs: list = []
    checked = {"days": 0, "counts": 0, "shares": 0, "medians": 0, "estimates": 0}

    def same(name: str, fieldwork, here):
        if fieldwork != here:
            differs.append({name: {"fieldwork": fieldwork, "here": here}})

    # 1. EACH CASE'S DAYS.
    mine = {c["id"]: {"incubation_days": days(c["dt_onset"], c["dt_end_exp"]),
                      "onset_to_death_days": days(c["dt_death"], c["dt_onset"])} for _, c in cases.iterrows()}
    for row in theirs["computedDays"]:
        for k in ("incubation_days", "onset_to_death_days"):
            checked["days"] += 1
            same(f"{row['id']}.{k}", row[k], mine.get(row["id"], {}).get(k))
    same("cases", len(theirs["computedDays"]), len(mine))

    # 2 AND 3. COUNTS, WITH THEIR SHARES WHERE ASKED.
    def counted(frame: pandas.DataFrame, table: dict):
        by, within = table["params"]["by"], (table["params"].get("share") or {}).get("within")
        sizes = frame.groupby(by, sort=False).size()
        here = {tuple(k if isinstance(k, tuple) else (k,)): int(v) for k, v in sizes.items()}
        stratum = {}
        if within is not None:
            for key, n in here.items():
                s = tuple(key[by.index(w)] for w in within)
                stratum[s] = stratum.get(s, 0) + n
        for row in table["rows"]:
            key = tuple(row[c] for c in by)
            if row.get("statistic", "rows") == "rows":
                checked["counts"] += 1
                same(f"count {key}", row["value"], here.get(key))
            else:
                checked["shares"] += 1
                s = tuple(key[by.index(w)] for w in within)
                same(f"share {key} {row['statistic']}", row["value"], half_up(here.get(key, 0), stratum.get(s)))
        same(f"groups {by}", len({tuple(r[c] for c in by) for r in table["rows"]}), len(here))
    counted(cases, theirs["byAgeClass"])
    counted(cases, theirs["bySex"])
    counted(links, theirs["perSource"])
    counted(pandas.DataFrame([{"incubation_days": v["incubation_days"]} for v in mine.values()]), theirs["byIncubation"])

    # 4. MEDIANS.
    def medians(frame: pandas.DataFrame, column: str, table: dict):
        by, exclude = table["params"]["by"], table["params"].get("excludeMissing", False)
        groups: dict = {}
        for _, r in frame.iterrows():
            groups.setdefault(tuple(r[c] for c in by), []).append(r[column])
        for row in table["rows"]:
            cells = groups.get(tuple(row[c] for c in by), [])
            present = [float(v) for v in cells if v != ""]
            here = None if (len(present) < len(cells) and not exclude) else median(present)
            checked["medians"] += 1
            same(f"median {tuple(row[c] for c in by)}", row["value"], here)
    dated = cases.assign(incubation_days=[mine[i]["incubation_days"] for i in cases["id"]])
    medians(dated, theirs["medianIncubation"]["params"]["total"], theirs["medianIncubation"])
    medians(links, fixture["declaredParameters"]["imports"]["links"]["value"], theirs["serialInterval"])

    # 5. THE TWO-BY-TWO.
    req = fixture["declaredParameters"]["twoByTwo"]
    e, u = cases[req["exposureColumn"]] == req["exposed"], cases[req["exposureColumn"]] == req["unexposed"]
    case, non = cases[req["outcomeColumn"]] == req["caseValue"], cases[req["outcomeColumn"]] == req["nonCaseValue"]
    a, b, c, d = int((e & case).sum()), int((e & non).sum()), int((u & case).sum()), int((u & non).sum())
    same("cells", theirs["twoByTwo"]["cells"],
         {"exposedCases": a, "exposedNonCases": b, "unexposedCases": c, "unexposedNonCases": d})
    z = NormalDist().inv_cdf(1 - (1 - req["level"] / 100) / 2)
    p1, p0 = a / (a + b), c / (c + d)
    rr, se_rr = p1 / p0, math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    orr, se_or = (a * d) / (b * c), math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    rd, se_rd = p1 - p0, math.sqrt(p1 * (1 - p1) / (a + b) + p0 * (1 - p0) / (c + d))
    here = {"risk ratio": (rr, rr * math.exp(-z * se_rr), rr * math.exp(z * se_rr)),
            "odds ratio": (orr, orr * math.exp(-z * se_or), orr * math.exp(z * se_or)),
            "risk difference": (rd, rd - z * se_rd, rd + z * se_rd)}
    for est in theirs["twoByTwo"]["estimates"]:
        mine_est = here.get(est["name"])
        if mine_est is None:
            differs.append({"estimate": est["name"], "problem": "not computed here"})
            continue
        for k, v in zip(("value", "lower", "upper"), mine_est):
            checked["estimates"] += 1
            if est[k] is None or abs(est[k] - v) > 1e-9 * max(1.0, abs(v)):
                differs.append({"estimate": f"{est['name']}.{k}", "fieldwork": est[k], "here": v})

    negative = sum(1 for v in mine.values() if v["incubation_days"].startswith("-"))
    return {
        "check": "51-mers-epi",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "source": {"commit": commit},
        "agrees": not differs,
        "criteria": "Exact: each case's days, every count, every share under the declared rounding, every median; "
                    "the two-by-two's cells exact and its estimates and limits within 1e-9 relative",
        "checked": checked,
        "differs": differs,
        "observed": {"exposureEndingAfterOnset": negative},
        "notEstablished": [
            f"That days from the last day of exposure to onset are an incubation period: {negative} cases have onset "
            "before the exposure window closed, and both sides keep them as written.",
            "That diff_dt_onset is a serial interval: the package does not document how links or their days were set.",
            "That the risk ratio by sex says anything about sex: its interval holds 1, and no study design is declared.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pandas": pandas.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"], report["checked"])
    for d in report["differs"][:20]:
        print(" ", d)
