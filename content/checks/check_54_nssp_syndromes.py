"""Check 54: Fieldwork's Apply ruleset on NSSP's syndrome definitions, against the published ESSENCE syntax read directly.

Fieldwork's syndromic surveillance example sorts made-up emergency department visits by four definitions of the National
Syndromic Surveillance Program (NSSP): ILI CCDD v1, CDC Broad Acute Respiratory DD v1, Norovirus v1 and CDC Measles CCDD
v1. Fieldwork does not read ESSENCE syntax: each definition was transcribed into Apply ruleset's own rules, with
"contains any of" and "has an item starting with any of", every bracketed pattern written out and every group a column.

**Independent.** This check does not read the transcription. It takes NSSP's syntax as the fixture carries it, copied
from the NSSP Knowledge Repository's pages, and evaluates it as ESSENCE does, by the rules CDC's "Free-text Coding in
NSSP-ESSENCE" states: each term a pattern searched for in the visit's text, ^ any run of characters, brackets one
character from a set, ANDNOT bound to the term before it, AND before OR, parentheses grouping, capitals ignored. A
definition over chief complaint and discharge diagnosis reads them as one field, the complaint and then the codes, each
preceded by a semicolon, as ESSENCE's combined field holds them. Nothing of Fieldwork's code or of its transcription is
read.

Criteria, fixed before running:

1. **The published ruleset agrees visit for visit**: for each of the four definitions, the visits Fieldwork flags with
   its ICD-10 and SNOMED CT ruleset are the visits the syntax selects, read with the ICD-10 and SNOMED CT columns.
2. **Every disagreement is one the transcription declares.** The transcription states where it reads differently: a
   caret inside a term ("sore ^throat") is read as both pieces present in any order, where ESSENCE requires the order.
   A disagreement of that kind is counted and listed, and does not fail the check; any other fails it.
3. **The ICD-11 ruleset** (Fieldwork's translation of NSSP's ICD-10-CM codes, checked against WHO's 2026-01 release) is
   read the same way with each ICD-10 code replaced by its ICD-11 codes from the translation table the fixture carries;
   the same two criteria hold.

What this cannot establish: that these definitions suit a made-up district, or any real one; that ICD-10 here (WHO's)
matches what NSSP wrote for ICD-10-CM, which is the point the example makes and not an error; that the ICD-11 translation
is the only reasonable one.
"""
from __future__ import annotations

import itertools
import json
import pathlib
import platform
import re
import sys
from datetime import datetime, timezone

from .fixtures import load_fixture

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "nssp-syndromes-001.json"
RESULT = HERE.parent / "results" / "check-54-nssp-syndromes.json"


# ---- ESSENCE, read directly -------------------------------------------------------------------------------------------

def pattern(term: str) -> re.Pattern:
    """A term as a regular expression: ^ any run of characters (and nothing at an end), [..] one character from a set."""
    body, out, i = term.strip(), "", 0
    starts, ends = body.startswith("^"), body.endswith("^") and len(body) > 1
    body = body[1 if starts else 0: -1 if ends else len(body)] if body != "^" else ""
    while i < len(body):
        ch = body[i]
        if ch == "^":
            out += ".*"; i += 1
        elif ch == "[":
            j = body.index("]", i)
            out += "[" + re.escape(body[i + 1:j]).replace("\\-", "-") + "]"; i = j + 1
        elif ch == "_":
            out += "."; i += 1
        else:
            out += re.escape(ch); i += 1
    return re.compile(("" if starts else "^") + out + ("" if ends else "$"), re.I | re.S)


def tokens(text: str) -> list[str]:
    out = []
    for raw in text.split(","):
        t = raw.strip()
        if not t:
            continue
        m = re.match(r"^(or|and|andnot)(\^.*)$", t, re.I)
        out += [m.group(1).lower(), m.group(2)] if m else [t.lower() if t.lower() in ("or", "and", "andnot") else t]
    return out


def evaluator(toks: list[str]):
    """A function of the field's text, by CDC's stated precedence: ANDNOT on the term before it, AND, then OR."""
    pos = 0

    def atom():
        nonlocal pos
        t = toks[pos]; pos += 1
        if t == "(":
            e = expr(); assert toks[pos] == ")"; pos += 1
            return e
        p = pattern(t)
        return lambda text: bool(p.search(text))

    def chain():
        nonlocal pos
        head, neg = atom(), []
        while pos < len(toks) and toks[pos] == "andnot":
            pos += 1; neg.append(atom())
        return lambda text: head(text) and not any(n(text) for n in neg)

    def conj():
        nonlocal pos
        cs = [chain()]
        while pos < len(toks) and toks[pos] == "and":
            pos += 1; cs.append(chain())
        return lambda text: all(c(text) for c in cs)

    def expr():
        nonlocal pos
        alts = [conj()]
        while pos < len(toks) and toks[pos] == "or":
            pos += 1; alts.append(conj())
        return lambda text: any(a(text) for a in alts)

    e = expr()
    assert pos == len(toks)
    return e


def sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"^(ChiefComplaints:|CC and DD:|Discharge Diagnosis:)\s*$", text.strip(), flags=re.M)
    if len(parts) == 1:
        return [("", text.strip())]
    return [(parts[i].rstrip(":"), parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def field(visit: dict, which: str, codes: str) -> str:
    """ESSENCE's fields: the complaint, the diagnosis codes, or both as one, each code after a semicolon."""
    dd = "".join(";" + c for c in (visit[codes] + ";" + visit["snomed"]).split(";") if c)
    return {"cc": visit["cc"], "dd": dd, "ccdd": visit["cc"] + dd}[which]


SCOPE = {"ili": "ccdd", "measles": "ccdd", "broad_respiratory": "dd"}
SECTION_SCOPE = {"ChiefComplaints": "cc", "CC and DD": "ccdd", "Discharge Diagnosis": "dd"}


def translated(syntax: str, table: list[dict]) -> str:
    """The syntax with each ICD-10 code term replaced by its ICD-11 codes, as the translation table says."""
    def keys(code10: str) -> list[str]:
        parts = code10.split()
        if "to" in parts:
            a, b = parts[0], parts[2]
            return [f"{a[0]}{n}" for n in range(int(a[1:]), int(b[1:]) + 1)]
        return parts
    lookup = {}
    for row in table:
        for k in keys(row["icd10cm"]):
            lookup.setdefault(k.replace(".", ""), []).extend(row["icd11"].split())

    def replace(match: re.Match) -> str:
        term = match.group(0)
        body = term.strip("^").strip()
        if not body.lower().startswith("[;/ ]"):
            return term
        code = re.sub(r"(;|\[;/ \])$", "", body[5:]).strip()
        if re.fullmatch(r"\d{6,}", code) or re.match(r"\d", code):
            return term  # a SNOMED CT concept, or ICD-9-CM, left as written
        spelled = [""]
        for lit, br in re.findall(r"([^\[]*)(?:\[([^\]]*)\])?", code):
            spelled = [s + lit for s in spelled]
            if br:
                chars = re.sub(r"(.)-(.)", lambda m: "".join(chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)), br)
                spelled = [s + c for s in spelled for c in chars if c != "|"]
        codes11 = []
        for s in spelled:
            bare = s.replace(".", "").upper()
            for k, v in lookup.items():
                if k.startswith(bare) or bare.startswith(k):
                    codes11 += v
        codes11 = list(dict.fromkeys(codes11))
        if not codes11:
            return "^[;/ ]NO-ICD-11^"  # a code the translation leaves out: it can match nothing
        return "(," + ",or,".join(f"^[;/ ]{c}^" for c in codes11) + ",)"
    return re.sub(r"\^[^,()]*\^?", replace, syntax)


# ---- the check -----------------------------------------------------------------------------------------------------

def run(fixture_path: pathlib.Path = FIXTURE) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared, rows = fixture["declaredParameters"], fixture["input"]["visits"]
    table = declared["icd11Translation"]
    report = {}
    for variant, codes, key in (("published", "icd10", "fieldworkIcd10"), ("icd11", "icd11", "fieldworkIcd11")):
        per = {}
        for name, syntax in declared["syntax"].items():
            text = syntax if variant == "published" else translated(syntax, table)
            parts = [(SECTION_SCOPE.get(s, SCOPE.get(name, "ccdd")), evaluator(tokens(body))) for s, body in sections(text)]
            mine = [v["id"] for v in rows if all(ev(field(v, scope, codes)) for scope, ev in parts)]
            theirs = [v["id"] for v in rows if v[key][name] == "yes"]
            only_here, only_fieldwork = sorted(set(mine) - set(theirs)), sorted(set(theirs) - set(mine))
            declared_order = [i for i in only_fieldwork if name == "ili" and order_only(rows, i)]
            per[name] = {"essence": len(mine), "fieldwork": len(theirs),
                         "onlyEssence": only_here[:20], "onlyFieldwork": only_fieldwork[:20],
                         "declaredDifference": len(declared_order),
                         "agrees": not only_here and len(only_fieldwork) == len(declared_order)}
        report[variant] = per
    return {
        "check": "54-nssp-syndromes",
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": {"id": fixture["fixtureId"], "sha256": digest,
                    "application": fixture["application"], "operation": fixture["operation"]},
        "criteria": "For each definition, the visits Fieldwork flags equal the visits the published ESSENCE syntax "
                    "selects, read directly, apart from differences the transcription declares (a caret inside a term "
                    "read as both pieces in any order); the same for the ICD-11 ruleset with the translation table applied",
        "visits": len(rows),
        "published": report["published"],
        "icd11": report["icd11"],
        "agrees": all(d["agrees"] for v in report.values() for d in v.values()),
        "notEstablished": [
            "That these definitions suit this made-up district, or any real one.",
            "That WHO's ICD-10, which the visits carry, is what NSSP wrote for ICD-10-CM: where they differ a definition "
            "finds nothing, which is what the example shows, not an error here.",
            "That the ICD-11 translation is the only reasonable one: this checks that Fieldwork applies it as written.",
            "How far an exclusion reaches. No visit here would be judged differently if an exclusion bound to everything "
            "before it rather than to the term before it (a complaint such as \"chills, denies any elevated temp\"), so "
            "the data cannot tell the two readings apart; a check that read exclusions the other way agrees here too.",
        ],
        "environment": {"runtime": f"{platform.python_implementation()} {platform.python_version()}",
                        "pyodide": "pyodide" in sys.modules},
    }


def order_only(rows: list[dict], visit_id: str) -> bool:
    """A visit flagged ILI by Fieldwork only because "sore" and a throat word are both there, in the other order."""
    cc = next(v["cc"] for v in rows if v["id"] == visit_id).lower()
    return "sore " in cc and re.search(r"th[or][ao][ar]t", cc) is not None and not re.search(r"sore .*th[or][ao][ar]t", cc)


if __name__ == "__main__":
    out = run()
    RESULT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("agrees:", out["agrees"])
    for variant in ("published", "icd11"):
        for name, d in out[variant].items():
            print(f"  {variant:9} {name:18} ESSENCE {d['essence']:5}  Fieldwork {d['fieldwork']:5}  "
                  f"{'OK' if d['agrees'] else 'DIFF'}  declared {d['declaredDifference']}")
