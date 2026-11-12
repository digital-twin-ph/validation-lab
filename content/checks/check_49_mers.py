"""Check 49: a whole worked example, end to end: MERS-CoV, South Korea, 2015, both workflows, against pandas.

Fieldwork experiment 208. The practitioner, 2026-11-12, after a warning read "189 records the rules could not read" of
162: *"What we need is a validation to make sure the results of counts and computations are accurate and precise."* One
check per widget, on its own fixture, could not have caught it: the number came from a whole example's chain. So here
every count and computed value the MERS example's two workflows produce is recomputed from its two source files.

**The data is not in this repository.** mers_korea_2015 (R package outbreaks; Cauchemez et al.) states no licence, so
it is used only in its own example repository. The fixture carries Fieldwork's results, the commit and each file's
digest; this check reads each file at that commit, from the repository checked out beside this one or from GitHub, and
verifies its digest before reading a row.

**Independent.** pandas reads the CSVs itself. Days are calendar differences of the dates; the tree is built from the
contacts by following each case's first listed source. Nothing here reads Fieldwork's tables.

Criteria, fixed before running, all exact (every value is a count or a whole number of days):

1. **Each case**: days from onset to diagnosis and from diagnosis to report, and its three verdicts against the
   declared targets (Met at most the target, Not met beyond it, No verdict where a date is missing; response has no
   date bound, so No verdict for every case).
2. **Each count**: cases by detection verdict and by notification verdict; links by source and by setting of exposure.
3. **Relate, one row per match**: the same (case, source) rows, with "none recorded" for a case no link names; the
   same numbers related, kept, and keys matching several rows.
4. **The tree**: cases, chains, links, cases naming no infector, undated cases, cases with several sources, further
   links, and each chain's size and generations.
5. **The data issues**: each counted issue's records, recomputed from the file: an empty onset, a response date no
   record carries, and a value written with spaces around it.

Values are read as Fieldwork declares it reads a table: key values without the spaces around them, each value so changed
counted as the data issue *Spaces trimmed* (the practitioner, 2026-11-12: "Trim, and say so", after this check found one,
"Family member ", that Fieldwork had trimmed and not said).

What this cannot establish: that the dates mean what 7-1-7 means by emergence, detection and notification; that the
contacts are the true transmission; that a report dated before its diagnosis is a fact rather than an error in the
source (counted here, not judged).

Design record: fieldwork/docs/experiments/208-accurate-and-precise-numbers.md
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import platform
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

import pandas
from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "mers-korea-001.json"
RESULT = HERE.parent / "results" / "check-49-mers.json"
CHECKOUT = HERE.parents[2] / "example-2015-mers-korea"


def source_bytes(item: dict, commit: str) -> bytes:
    """The file at the pinned commit: the checkout beside this repository if it has it, else GitHub. Digest first."""
    data = None
    if CHECKOUT.exists():
        try:
            data = subprocess.run(["git", "-C", str(CHECKOUT), "show", f"{commit}:{item['path']}"],
                                  check=True, capture_output=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            data = None
    if data is None and "pyodide" in sys.modules:
        from pyodide.http import open_url  # the browser kernel: a synchronous fetch, decoded as text
        data = open_url(item["url"]).read().encode("utf-8")
    if data is None:
        with urllib.request.urlopen(item["url"], timeout=60) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != item["sha256"]:
        raise ValueError(f"{item['path']} at {commit[:7]} has digest {digest[:12]}, not {item['sha256'][:12]}: not read")
    return data


def days(later: str, earlier: str):
    if not later or not earlier:
        return None
    return int((pandas.Timestamp(later) - pandas.Timestamp(earlier)).days)


def verdict(d, target: int) -> str:
    return "No verdict" if d is None else "Met" if d <= target else "Not met"


def fold(key: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(key).lower())


def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared, theirs = fixture["declaredParameters"], fixture["output"]
    commit = fixture["source"].split(" at ")[1].split(":")[0]
    files = {f["path"]: source_bytes(f, commit) for f in fixture["input"]["files"]}
    raw_cases = pandas.read_csv(io.BytesIO(files["data/mers_korea_2015_linelist.csv"]), dtype=str, keep_default_na=False)
    raw_contacts = pandas.read_csv(io.BytesIO(files["data/mers_korea_2015_contacts.csv"]), dtype=str, keep_default_na=False)
    # AS FIELDWORK DECLARES IT READS A TABLE: a value without the spaces around it, each one so changed counted as a data
    # issue (Spaces trimmed). Read raw here, so the trimmed values are counted from the file and not taken on trust.
    cases, contacts = (frame.apply(lambda column: column.str.strip()) for frame in (raw_cases, raw_contacts))
    differs: list = []

    # 1. EACH CASE.
    bound, targets = declared["timeliness"]["bindings"], declared["timeliness"]["targets"]
    onset, diag, report = bound["fw:emergenceDate"], bound["fw:detectionDate"], bound["fw:notificationDate"]
    mine = {}
    for _, c in cases.iterrows():
        detect, notify = days(c[diag], c[onset]), days(c[report], c[diag])
        mine[c["id"]] = {"days_to_detect": detect, "days_to_notify": notify,
                         "detected_within_target": verdict(detect, targets["detectionTarget"]),
                         "notified_within_target": verdict(notify, targets["notificationTarget"]),
                         "responded_within_target": "No verdict"}
    for case in theirs["cases"]:
        here = mine.get(case["id"])
        if here is None:
            differs.append({"case": case["id"], "problem": "not in the line list"})
            continue
        for k, v in here.items():
            if case[k] != v:
                differs.append({"case": case["id"], "field": k, "fieldwork": case[k], "here": v})
    if len(theirs["cases"]) != len(mine):
        differs.append({"cases": {"fieldwork": len(theirs["cases"]), "here": len(mine)}})

    # 2. EACH COUNT.
    def compare(name: str, theirs_counts: dict, here: pandas.Series):
        got = {str(k): int(v) for k, v in here.items()}
        if got != {str(k): int(v) for k, v in theirs_counts.items()}:
            differs.append({"counts": name, "fieldwork": theirs_counts, "here": got})
    frame = pandas.DataFrame.from_dict(mine, orient="index")
    compare("detected", theirs["detected"], frame["detected_within_target"].value_counts())
    compare("notified", theirs["notified"], frame["notified_within_target"].value_counts())
    compare("sources", theirs["sources"], contacts["from"].value_counts())
    compare("settings", theirs["settings"], contacts["exposure"].value_counts())

    # 3. RELATE, ONE ROW PER MATCH.
    relate = declared["relate"]
    by_key: dict = {}
    for _, link in contacts.iterrows():
        by_key.setdefault(fold(link[relate["rightOn"]]), []).append(link[relate["bring"]])
    rows, related, kept, several, added = [], 0, 0, 0, 0
    for _, c in cases.iterrows():
        found = by_key.get(fold(c[relate["on"]]), [])
        if found:
            related += 1
            several += len(found) > 1
            added += len(found) - 1
            rows += [(c["id"], f) for f in found]
        else:
            kept += 1
            rows.append((c["id"], relate["unmatched"]))
    theirs_rows = sorted((r["id"], r["from"]) for r in theirs["related"]["rows"])
    if sorted(rows) != theirs_rows:
        differs.append({"relate": "rows", "fieldworkRows": len(theirs_rows), "hereRows": len(rows)})
    summary = theirs["related"]["summary"] or {}
    for k, v in {"offered": len(cases), "related": related, "kept": kept}.items():
        if summary.get(k) != v:
            differs.append({"relate": k, "fieldwork": summary.get(k), "here": v})
    for k, v in {"keys": several, "addedRows": added}.items():
        if (summary.get("several") or {}).get(k) != v:
            differs.append({"relate": f"several.{k}", "fieldwork": (summary.get("several") or {}).get(k), "here": v})

    # 4. THE TREE, from each case's first listed source.
    ids = list(cases["id"])
    known = set(ids)
    sources = {i: by_key.get(fold(i), []) for i in ids}
    parent = {i: (s[0] if s else None) for i, s in sources.items()}

    def root_and_depth(i: str):
        depth, seen = 0, {i}
        while parent[i] is not None and parent[i] in known:
            i = parent[i]
            depth += 1
            if i in seen:
                return None, depth
            seen.add(i)
        return i, depth
    chains: dict = {}
    for i in ids:
        r, d = root_and_depth(i)
        chain = chains.setdefault(r, {"size": 0, "deepest": 0})
        chain["size"] += 1
        chain["deepest"] = max(chain["deepest"], d)
    counts = {"cases": len(ids), "chains": len(chains),
              "noInfector": sum(1 for i in ids if not sources[i]),
              "unknownInfector": sum(1 for i in ids if parent[i] is not None and parent[i] not in known),
              "undated": int((cases[bound["fw:emergenceDate"]] == "").sum()),
              "links": sum(1 for i in ids if parent[i] in known),
              "severalSources": sum(1 for i in ids if len(sources[i]) > 1),
              "furtherLinks": sum(len(s) - 1 for s in sources.values() if len(s) > 1)}
    for k, v in counts.items():
        if theirs["tree"]["counts"].get(k) != v:
            differs.append({"tree": k, "fieldwork": theirs["tree"]["counts"].get(k), "here": v})
    for chain in theirs["tree"]["chains"]:
        here = chains.get(chain["root"])
        if here is None or here["size"] != chain["size"] or here["deepest"] + 1 != chain["generations"]:
            differs.append({"chain": chain["root"], "fieldwork": [chain["size"], chain["generations"]],
                            "here": None if here is None else [here["size"], here["deepest"] + 1]})

    # 5. THE DATA ISSUES, each counted from the file.
    def recount(issue: dict):
        column = issue["column"]
        if issue["kind"] == "ValueTrimmed":
            raw = raw_cases if column in raw_cases else raw_contacts
            changed = (raw[column] != raw[column].str.strip()) & (raw[column].str.strip() != "")
            return int(changed.sum()), len(raw)
        if issue["kind"] in ("KeyAbsent", "ValueEmpty", "ValueAbsent"):
            return int((cases[column] == "").sum()) if column in cases else None, len(cases)
        if issue["kind"] == "FieldMissing":
            return (len(cases) if column not in cases else 0), len(cases)
        return None, None
    issues_checked = 0
    for issue in theirs["dataIssues"]:
        if "count" not in issue:
            continue
        count, of = recount(issue)
        issues_checked += 1
        if (count, of) != (issue["count"], issue["of"]):
            differs.append({"issue": issue, "here": {"count": count, "of": of}})

    report_before_diagnosis = sum(1 for v in mine.values() if v["days_to_notify"] is not None and v["days_to_notify"] < 0)
    return {
        "check": "49-mers",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "source": {"commit": commit, "files": {p: hashlib.sha256(b).hexdigest() for p, b in files.items()}},
        "agrees": not differs,
        "criteria": "Exact: each case's days and three verdicts; the verdict, source and setting counts; Relate's rows "
                    "and its related, kept and several counts; the tree's counts and each chain's size and generations; "
                    "each counted data issue",
        "checked": {"cases": len(theirs["cases"]), "countTables": 4, "relateRows": len(theirs_rows),
                    "treeCounts": len(counts), "chains": len(theirs["tree"]["chains"]), "dataIssues": issues_checked},
        "differs": differs,
        "observed": {"reportBeforeDiagnosis": report_before_diagnosis},
        "notEstablished": [
            "That dt_onset, dt_diag and dt_report are 7-1-7's emergence, detection and notification: the bindings are "
            "the practitioner's, and both sides read the same columns.",
            "That the contacts are the true transmission, or that a case's first listed source is its infector.",
            f"That a report dated before its diagnosis ({report_before_diagnosis} cases here) is a fact and not an error "
            "in the source: both sides count it as a negative interval and so as Met.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pandas": pandas.__version__, "pyodide": "pyodide" in sys.modules},
    }


if __name__ == "__main__":
    report = run()
    RESULT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print("agrees:", report["agrees"])
    for d in report["differs"][:20]:
        print(" ", d)
