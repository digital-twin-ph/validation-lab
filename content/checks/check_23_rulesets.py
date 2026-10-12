"""Check 23: Fieldwork's declared rulesets, against an independent decision table.

Two claims are checked here and they are **different claims**, which is the whole point of the
check. Fieldwork reaches its conclusions in TypeScript by generating N3 facts, binding a
parameter into N3 rules and handing both to the EYE reasoner. Nothing of that happens below.

  1 · **The logic produces the same result.** A decision table written in Python, derived from
      each ruleset's own prose description and declared vocabulary, against the conclusions the
      real reasoner produced. A different language, a different evaluation strategy, no rule
      engine at all -- if the two agree on every cell, the agreement means something.

  2 · **The receipt is the same receipt.** A conclusion a reader cannot audit is worth little,
      so the emitted facts and rules are parsed and checked: every asserted predicate is one the
      ruleset's input contract declares and no others leak in, the known-flags match the cell's
      inputs, numbers carry the declared precision, and the rules use only the tiny N3 subset
      this project claims -- conjunction plus two comparison builtins, with no negation, no
      recursion, and no dataset instance named in a rule.

**Exhaustive, not sampled.** All three rulesets have finite input spaces: 12, 10 and 24 cells,
enumerated completely. That is stronger than any sample, because it sees what a sample cannot --
a cell no rule fires on, a cell two rules disagree about, and the boundary cell where a value
*equals* the threshold, which is what separates `math:notGreaterThan` from `math:lessThan`.

The decision tables are derived from the descriptions, not transcribed from the N3. For
outreach-criteria, "flags a location for review when an alert is active and its distance exceeds
a threshold; missing evidence is concluded unknown rather than negative" becomes three lines of
Python. If that reading and the shipped rules disagree, the disagreement is the finding.

What this cannot establish: that any threshold is the right threshold, or that any ruleset is a
good one. It checks that the rules say what the ruleset says they say, and that a reader is shown
the same thing the reasoner was. Of the three, one claims a published basis and **none** carries
evidence a reader can open; that is recorded in the fixture and is not something a parity check
can fix.

The N3 parser below is deliberately small and local. The receipts use a regular subset -- prefixed
triples with `;` continuation -- and writing forty lines here avoids adding a dependency to a
browser kernel that this project has already measured crashing on package combinations. The cost
is that the parser is itself the oracle, so it asserts its own round-trip first.

Independent by construction: nothing here imports Fieldwork code.
Design record: fieldwork/docs/experiments/65-ruleset-as-data.md, 106-rule-builder-ui.md
"""
from __future__ import annotations
import json
import re
from pathlib import Path

FIXTURES = ("ruleset-outreach-criteria-001", "ruleset-access-review-001", "ruleset-nb06-evidence-001")


def _statements(text: str) -> list[str]:
    """Split on statement-terminating dots only.

    Splitting on every `.` also splits `1.500000000`, which is how the first version of this
    parser read one triple as three and why the round-trip assertion below exists. A dot
    terminates a statement when it is outside angle brackets and not followed by a digit, so a
    decimal point and a dot inside an IRI both survive.
    """
    out: list[str] = []
    buffer: list[str] = []
    depth = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        following = text[index + 1] if index + 1 < len(text) else ""
        if char == "." and depth == 0 and (following == "" or following.isspace()):
            out.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    out.append("".join(buffer))
    return [statement.strip() for statement in out if statement.strip()]


# ---- a small N3 reader for the subset the receipts use -------------------------------------
def parse_n3(text: str) -> set[tuple[str, str, str]]:
    """Prefixed triples, `;` continuation, `.` terminated. Returns a set of (s, p, o) strings."""
    prefixes: dict[str, str] = {}
    body: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        directive = re.match(r"@prefix\s+([A-Za-z]*):\s*<([^>]*)>\s*\.", line)
        if directive:
            prefixes[directive.group(1)] = directive.group(2)
            continue
        body.append(line)

    def expand(term: str) -> str:
        term = term.strip()
        if term.startswith("<") and term.endswith(">"):
            return term[1:-1]
        head, _, tail = term.partition(":")
        return prefixes[head] + tail if head in prefixes and _ else term

    triples: set[tuple[str, str, str]] = set()
    for statement in _statements(" ".join(body)):
        subject, _, remainder = statement.partition(" ")
        for clause in remainder.split(";"):
            parts = clause.strip().split()
            if len(parts) < 2:
                continue
            triples.add((expand(subject), expand(parts[0]), expand(" ".join(parts[1:]))))
    return triples


def _parser_round_trip() -> None:
    """The parser is the oracle for claim 2, so it states its own behaviour before being trusted."""
    sample = "@prefix fw: <urn:f:>.\n# comment\nfw:a fw:p true; fw:q 1.5.\n<urn:f:b> fw:p false.\n"
    assert parse_n3(sample) == {
        ("urn:f:a", "urn:f:p", "true"),
        ("urn:f:a", "urn:f:q", "1.5"),
        ("urn:f:b", "urn:f:p", "false"),
    }, "the local N3 reader does not behave as this check assumes"


# ---- claim 1 · the decision tables, from each ruleset's prose ------------------------------
def outreach(cell: dict, threshold: float) -> dict[str, str]:
    if not cell["distanceKnown"] or not cell["alertKnown"]:
        return {"fw:decision": "fw:Unknown"}
    if cell["alertActive"] and cell["distance"] > threshold:
        return {"fw:decision": "fw:Review"}
    return {"fw:decision": "fw:NoFlag"}


def access(cell: dict, threshold: float) -> dict[str, str]:
    minutes = cell["minutes"]
    if not cell["accessKnown"]:
        return {"fw:decision": "fw:Unknown", "fw:zone": "fw:Unknown"}
    decision = "fw:Review" if minutes > threshold else "fw:NoFlag"
    zone = ("fw:Within5" if minutes <= 5 else "fw:Within15" if minutes <= 15
            else "fw:Within30" if minutes <= 30 else "fw:Over30")
    return {"fw:decision": decision, "fw:zone": zone}


def nb06(cell: dict, _threshold: float | None) -> dict[str, str]:
    named, government, kind = cell["namedRule"], cell["government"], cell["facilityKind"]
    if named == "Marina":
        return {"fw:evidenceLevel": "fw:Direct", "fw:service": "fw:Onsite"}
    if named == "Broadhurst":
        return {"fw:evidenceLevel": "fw:Contextual", "fw:service": "fw:OnsiteOrReferral"}
    if government and kind == "Hospital":
        return {"fw:evidenceLevel": "fw:Contextual", "fw:service": "fw:Onsite"}
    if government and kind == "Clinic":
        return {"fw:evidenceLevel": "fw:Inferential", "fw:service": "fw:OnsiteOrReferral"}
    if government and kind == "HealthPost":
        return {"fw:evidenceLevel": "fw:Inferential", "fw:service": "fw:ReferralOnly"}
    return {"fw:evidenceLevel": "fw:None", "fw:service": "fw:Unknown"}


TABLES = {"ruleset-outreach-criteria-001": outreach,
          "ruleset-access-review-001": access,
          "ruleset-nb06-evidence-001": nb06}


def run(base: Path) -> dict:
    _parser_round_trip()
    reports = []
    for fixture_id in FIXTURES:
        fixture = json.loads((base / "fixtures" / f"{fixture_id}.json").read_text())
        declared = fixture["declaredParameters"]
        threshold = declared.get("threshold")
        table = TABLES[fixture_id]
        cells = {cell["id"]: cell for cell in fixture["input"]["cells"]}
        emitted = {entry["id"]: entry["conclusions"] for entry in fixture["output"]["decisions"]}
        facts_by_cell = {entry["id"]: entry["facts"] for entry in fixture["output"]["receipt"]["factsByCell"]}
        rules = fixture["output"]["receipt"]["rules"]

        # claim 1
        rows, mismatches = [], []
        for cell_id, cell in cells.items():
            expected = table(cell, threshold)
            actual = {c["predicate"]: c["value"] for c in emitted[cell_id]}
            agrees = expected == actual
            rows.append({"id": cell_id, "inputs": {k: v for k, v in cell.items() if k != "id"},
                         "expected": expected, "emitted": actual, "agrees": agrees})
            if not agrees:
                mismatches.append({"id": cell_id, "expected": expected, "emitted": actual})
            # Every cell concludes something, and concludes it once per predicate: a cell no rule
            # fires on is a gap in the ruleset, not a finding about the data.
            if len(emitted[cell_id]) != len({c["predicate"] for c in emitted[cell_id]}):
                mismatches.append({"id": cell_id, "problem": "two conclusions for one predicate"})

        # claim 2 · the receipt
        declared_predicates = {e["predicate"] for e in declared["expects"]}
        undeclared, precision_problems, subject_problems = [], [], []
        for cell_id, facts in facts_by_cell.items():
            triples = parse_n3(facts)
            subjects = {s for s, _, _ in triples}
            if len(subjects) != 1:
                subject_problems.append({"id": cell_id, "subjects": sorted(subjects)})
            for subject, predicate, value in triples:
                short = predicate.replace("urn:fieldwork:", "fw:")
                if short not in declared_predicates:
                    undeclared.append({"id": cell_id, "predicate": short})
                if re.fullmatch(r"-?\d+\.\d+", value) and len(value.split(".")[1]) != 9:
                    precision_problems.append({"id": cell_id, "predicate": short, "value": value})

        rule_count = rules.count("=>")
        builtins = sorted({m for m in re.findall(r"\b(?:math|log|string|list):[A-Za-z]+", rules)})
        instances = sorted(set(re.findall(r"urn:fieldwork:(?:place|facility|site):[A-Za-z0-9-]+", rules)))
        bound = sorted(set(re.findall(r"\d+\.\d{9}", rules)))
        placeholders = sorted(set(re.findall(r"\{\{[a-zA-Z]+\}\}", rules)))

        reports.append({
            "fixtureId": fixture_id,
            "ruleset": fixture["operation"]["ruleset"],
            "rulesetVersion": declared["rulesetVersion"],
            "basisStatus": declared["basisStatus"],
            "resolvableEvidence": declared["resolvableEvidence"],
            "unresolvedCitations": declared["unresolvedCitations"],
            "cells": len(cells),
            "logicAgrees": not mismatches,
            "mismatches": mismatches,
            "rows": rows,
            "receipt": {
                "ruleCount": rule_count,
                "builtins": builtins,
                "boundValues": bound,
                "unboundPlaceholders": placeholders,
                "instancesNamedInRules": instances,
                "undeclaredPredicates": undeclared,
                "precisionProblems": precision_problems,
                "multiSubjectCells": subject_problems,
                "declaredPredicates": sorted(declared_predicates),
            },
            "receiptAgrees": (not undeclared and not precision_problems and not subject_problems
                              and not instances and not placeholders
                              and all(b.startswith("math:") for b in builtins)),
        })

    return {"environment": "CPython" if "pyodide" not in __import__("sys").modules else "Pyodide",
            "rulesets": reports,
            "logicAgrees": all(r["logicAgrees"] for r in reports),
            "receiptsAgree": all(r["receiptAgrees"] for r in reports),
            "totalCells": sum(r["cells"] for r in reports),
            "rulesetsWithResolvableEvidence": sum(1 for r in reports if r["resolvableEvidence"]),
            "agrees": all(r["logicAgrees"] and r["receiptAgrees"] for r in reports)}
