"""Check 26: Fieldwork Deduplicate point records against rapidfuzz, jellyfish and a geodesic.

Cross-source record linkage: two layers of health-facility records, a blocking distance, a name
comparison, two binary contributions to a score, three classes from two thresholds, and a cluster
rule that admits at most one record per source.

**Why this widget and why now.** It is on the weakest rung of Fieldwork's own evidence ladder and
no worked example exercises it, so every claim about it rested on this repository's tests alone.

**Genuinely independent, four ways.** The name comparison is recomputed by rapidfuzz (C++) and by
jellyfish (Rust), which are separate implementations by separate authors; the normalisation is
recomputed from the declared rule in plain Python; the distances are recomputed as WGS84
geodesics by pyproj, where Fieldwork measures a great circle on a sphere; and the blocking,
scoring, classification and clustering are reimplemented here from `declaredParameters` alone.
Fieldwork's intermediate values are in `output` and are the thing compared, never an input.

Criteria, fixed before running:

1. **Name similarity** to within 1e-9 of rapidfuzz, with jellyfish carried as a third opinion.
2. **Normalised names** exactly, in both the exact and the fuzzy mode.
3. **Distances** to within 1% of the geodesic. The widget declares a spherical approximation
   that experiment 101 audits at -0.11% to +0.56%, so an exact comparison would be measuring
   the sphere, not the implementation. Every pair in the fixture is at least 10 m clear of both
   distance thresholds, which is what lets the classes below be compared exactly anyway.
4. **Blocked and compared counts** exactly, including that same-source pairs are neither.
5. **Each pair's two agreements, score and class** exactly.
6. **The cluster rule**: the merged count, the output record set, and every `mergedFrom`.

What this cannot establish: **what the thresholds should be.** 0.88, 500 m and 50 m are proposals
in the release, not measurements. Answering that needs records whose true identity is known, and
these records are constructed -- designed so every branch fires at least once, which downloaded
records would do only by luck. It also cannot establish that the greedy cluster order is the
right one; see the note on `osm-2` below, which is a finding about the rule rather than about
the implementation of it.

Design record: fieldwork/docs/experiments/41-validation-lab.md
"""
import json
import platform
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .fixtures import load_fixture

import jellyfish
from pyproj import Geod
from rapidfuzz.distance import JaroWinkler

ROOT = Path(__file__).resolve().parent.parent
GEOD = Geod(ellps="WGS84")
SIMILARITY_TOLERANCE = 1e-9
DISTANCE_TOLERANCE = 0.01


def normalise(value, mode: str) -> str:
    """The declared rule, reimplemented: NFKC, trimmed, lower case; fuzzy also replaces every run
    of characters that are neither letters nor numbers with one space.

    Python's `str.isalnum` is not identical to JavaScript's `\\p{L}\\p{N}` -- it also admits
    characters of category No and Nl -- so a name containing a Roman numeral or a circled digit
    could normalise differently. None of the names here contain one, and the comparison is over
    the names actually present.
    """
    if not isinstance(value, str):
        return ""
    base = unicodedata.normalize("NFKC", value).strip().lower()
    if mode != "fuzzy":
        return base
    collapsed = "".join(ch if ch.isalnum() else " " for ch in base)
    return re.sub(r" +", " ", collapsed).strip()


def run(fixture_path: Path) -> dict:
    fixture, digest = load_fixture(fixture_path)
    declared = fixture["declaredParameters"]
    reported = fixture["output"]
    name_field = declared["nameField"]
    mode = declared["nameMatch"]

    # ---- the records, as the fixture states them -------------------------------------------
    records = []
    for layer in fixture["input"]["layers"]:
        for feature in layer["features"]:
            records.append({"source": layer["sourceNodeId"], "id": feature["id"],
                            "name": feature["name"], "coordinates": feature["coordinates"]})
    placed = [r for r in records if r["coordinates"]]

    # ---- 1. the name comparison, two independent implementations ----------------------------
    similarity_rows = []
    for pair in reported["nameSimilarities"]:
        a, b = pair["a"], pair["b"]
        rf = JaroWinkler.similarity(a, b) if a and b else 0.0
        jf = jellyfish.jaro_winkler_similarity(a, b) if a and b else 0.0
        similarity_rows.append({
            "a": a, "b": b,
            "fieldwork": pair["similarity"],
            "rapidfuzz": rf,
            "jellyfish": jf,
            "agreesWithRapidfuzz": abs(pair["similarity"] - rf) < SIMILARITY_TOLERANCE,
            "referencesAgree": abs(rf - jf) < SIMILARITY_TOLERANCE,
        })

    # ---- 2. the normalisation ----------------------------------------------------------------
    by_id = {r["id"]: r for r in records}
    normalisation_rows = []
    for row in reported["normalisedNames"]:
        source_name = by_id[row["id"]]["name"]
        normalisation_rows.append({
            "id": row["id"],
            "exactAgrees": row["exact"] == normalise(source_name, "exact"),
            "fuzzyAgrees": row["fuzzy"] == normalise(source_name, "fuzzy"),
            "fuzzyReference": normalise(source_name, "fuzzy"),
            "fuzzyFieldwork": row["fuzzy"],
        })

    # ---- 3-5. blocking, comparison, scoring and classification -------------------------------
    def geodesic_metres(a, b) -> float:
        return GEOD.inv(a[0], a[1], b[0], b[1])[2]

    reference_pairs = {}
    blocked = compared = 0
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a, b = placed[i], placed[j]
            if a["source"] == b["source"]:
                continue  # cross-source only: neither compared nor blocked
            metres = geodesic_metres(a["coordinates"], b["coordinates"])
            if metres > declared["blockDistanceM"]:
                blocked += 1
                continue
            compared += 1
            left, right = normalise(a["name"], mode), normalise(b["name"], mode)
            both_named = bool(left) and bool(right)
            similarity = (JaroWinkler.similarity(left, right) if mode == "fuzzy"
                          else (1.0 if left == right else 0.0)) if both_named else None
            name_agrees = both_named and similarity >= declared["fuzzyThreshold"] \
                if mode == "fuzzy" else both_named and left == right
            near_agrees = metres <= declared["nearDistanceM"]
            score = int(name_agrees) + int(near_agrees)
            classification = ("match" if score >= declared["matchThreshold"]
                              else "review" if score >= declared["reviewThreshold"]
                              else "non-match")
            key = "|".join(sorted([f"{a['source']}:{a['id']}", f"{b['source']}:{b['id']}"]))
            reference_pairs[key] = {"metres": metres, "similarity": similarity,
                                    "nameAgrees": name_agrees, "nearAgrees": near_agrees,
                                    "score": score, "classification": classification}

    pair_rows = []
    for candidate in reported["candidates"]:
        reference = reference_pairs.get(candidate["key"])
        if reference is None:
            pair_rows.append({"key": candidate["key"], "present": False, "agrees": False})
            continue
        spread = abs(candidate["metres"] - reference["metres"])
        pair_rows.append({
            "key": candidate["key"],
            "present": True,
            "metresFieldwork": candidate["metres"],
            "metresReference": reference["metres"],
            "metresRelative": spread / reference["metres"] if reference["metres"] else 0.0,
            "metresAgrees": spread <= DISTANCE_TOLERANCE * max(reference["metres"], 1e-9),
            "nameAgreesAgrees": candidate["nameAgrees"] == reference["nameAgrees"],
            "nearAgreesAgrees": candidate["nearAgrees"] == reference["nearAgrees"],
            "scoreAgrees": candidate["score"] == reference["score"],
            "classFieldwork": candidate["classification"],
            "classReference": reference["classification"],
            "classAgrees": candidate["classification"] == reference["classification"],
        })
    for row in pair_rows:
        row["agrees"] = bool(row["present"] and row["metresAgrees"] and row["nameAgreesAgrees"]
                             and row["nearAgreesAgrees"] and row["scoreAgrees"] and row["classAgrees"])

    counts_agree = {
        "compared": reported["counts"]["compared"] == compared,
        "blocked": reported["counts"]["blocked"] == blocked,
        "inputCount": reported["counts"]["inputCount"] == len(records),
        "candidateRows": len(reported["candidates"]) == len(reference_pairs),
    }

    # ---- 6. the cluster rule -----------------------------------------------------------------
    # Accepted in order of score descending, then distance ascending, then key -- and a cluster
    # holds at most one record from each source, so an edge that would add a second is refused.
    parent = {f"{r['source']}:{r['id']}": f"{r['source']}:{r['id']}" for r in placed}
    sources = {k: {k.split(":")[0]} for k in parent}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    order = sorted(reference_pairs.items(),
                   key=lambda kv: (-kv[1]["score"], kv[1]["metres"], kv[0]))
    merged = 0
    refused = []
    for key, pair in order:
        if pair["classification"] != "match":
            continue
        left_key, right_key = key.split("|")
        left, right = find(left_key), find(right_key)
        if left == right:
            continue
        union = sources[left] | sources[right]
        if len(union) < len(sources[left]) + len(sources[right]):
            refused.append(key)
            continue
        parent[right] = left
        sources[left] = union
        del sources[right]
        merged += 1

    groups = {}
    for record in placed:
        groups.setdefault(find(f"{record['source']}:{record['id']}"), []).append(record)
    reference_records = {}
    for held in groups.values():
        kept = held[0]
        reference_records[kept["id"]] = (" ".join(f"{r['source']}:{r['id']}" for r in held)
                                         if len(held) > 1 else None)
    for record in records:
        if not record["coordinates"]:
            reference_records[record["id"]] = None

    reported_records = {r["id"]: r["mergedFrom"] for r in reported["records"]}
    cluster = {
        "mergedFieldwork": reported["counts"]["merged"],
        "mergedReference": merged,
        "mergedAgrees": reported["counts"]["merged"] == merged,
        "refusedEdges": refused,
        "refusedCount": len(refused),
        "outputRecordsAgree": set(reported_records) == set(reference_records),
        "mergedFromAgrees": reported_records == reference_records,
        "outputCountFieldwork": reported["counts"]["outputRecords"],
        "outputCountReference": len(reference_records),
    }

    similarity_agrees = all(row["agreesWithRapidfuzz"] for row in similarity_rows)
    normalisation_agrees = all(row["exactAgrees"] and row["fuzzyAgrees"] for row in normalisation_rows)
    pairs_agree = all(row["agrees"] for row in pair_rows)
    pipeline_agrees = (normalisation_agrees and pairs_agree and all(counts_agree.values())
                       and cluster["mergedAgrees"] and cluster["mergedFromAgrees"]
                       and cluster["outputRecordsAgree"])
    diverging = [row for row in similarity_rows if not row["agreesWithRapidfuzz"]]

    return {
        "check": "26-deduplicate",
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "runtime": f"{platform.python_implementation()} {platform.python_version()} on {platform.system()} {platform.machine()}",
            "isPyodide": sys.platform == "emscripten",
            "rapidfuzz": __import__("importlib.metadata", fromlist=["version"]).version("rapidfuzz"),
            "jellyfish": __import__("importlib.metadata", fromlist=["version"]).version("jellyfish"),
            "pyproj": __import__("pyproj").__version__,
        },
        "fixture": {
            "id": fixture["fixtureId"],
            "sha256": digest,
            "application": fixture["application"],
            "operation": fixture["operation"],
            "declaredThresholds": {k: declared[k] for k in
                                   ("fuzzyThreshold", "blockDistanceM", "nearDistanceM",
                                    "matchThreshold", "reviewThreshold")},
        },
        "criterion": (
            "name similarity within 1e-9 of rapidfuzz; normalised names exact in both modes; "
            "distances within 1% of a WGS84 geodesic; blocked and compared counts exact; each "
            "pair's two agreements, score and class exact; and the merged count, output record "
            "set and every mergedFrom exact"
        ),
        "records": len(records),
        "placedRecords": len(placed),
        "nameSimilarities": similarity_rows,
        "normalisation": normalisation_rows,
        "counts": {"comparedReference": compared, "blockedReference": blocked,
                   "comparedFieldwork": reported["counts"]["compared"],
                   "blockedFieldwork": reported["counts"]["blocked"], "agree": counts_agree},
        "pairs": pair_rows,
        "cluster": cluster,
        "nameSimilarityAgrees": similarity_agrees,
        "pipelineAgrees": pipeline_agrees,
        "divergences": [
            {"case": f"{row['a']} / {row['b']}", "fieldwork": row["fieldwork"],
             "rapidfuzz": row["rapidfuzz"], "jellyfish": row["jellyfish"],
             "difference": abs(row["fieldwork"] - row["rapidfuzz"]),
             "cause": (
                 "The raw count of matched characters in a different order is halved. Fieldwork "
                 "halves it exactly (3 becomes 1.5); rapidfuzz and jellyfish halve it with "
                 "integer division (3 becomes 1). The two references agree with each other, so "
                 "this is a convention and not a slip in either. It can only arise when that raw "
                 "count is odd, which needs a cycle of odd length among the matched characters: "
                 "every published reference pair has an even count, so no published value can "
                 "detect it. Unreached by any name pair in this fixture's two layers."
             )}
            for row in diverging
        ],
        "notEstablished": (
            "What the thresholds should be. 0.88, 500 m and 50 m are proposals in the release, not "
            "measurements, and measuring them needs records whose true identity is known. These are "
            "constructed so that every branch fires. Nor does it establish that the greedy cluster "
            "order picks the right partner: osm-2 'Ospital ng Maynila Medical Center Annex' sits 2 m "
            "from the Overture record for the main hospital and 20 m from its own layer's record for "
            "it, and distance-first ordering pairs the Annex with the main hospital while refusing "
            "the pair a reader would choose. Both implementations do this, because both follow the "
            "declared rule. It is a finding about the rule."
        ),
        "agrees": bool(similarity_agrees and pipeline_agrees),
    }


if __name__ == "__main__":
    result = run(ROOT / "fixtures" / "deduplicate-facilities-001.json")
    out = ROOT / "results" / "check-26-deduplicate.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"check 26: agrees={result['agrees']} "
          f"(names={result['nameSimilarityAgrees']}, pipeline={result['pipelineAgrees']}) "
          f"over {result['records']} records -> {out.relative_to(ROOT.parent)}")
    print(f"  {result['counts']['comparedFieldwork']} pairs compared, "
          f"{result['counts']['blockedFieldwork']} blocked, "
          f"{result['cluster']['mergedFieldwork']} merged, "
          f"{result['cluster']['refusedCount']} match(es) refused by the one-per-source rule")
    for row in result["pairs"]:
        if not row["agrees"]:
            print(f"  DISAGREES {row['key']}: {row.get('classFieldwork')} vs {row.get('classReference')}")
    for d in result["divergences"]:
        print(f"  name similarity diverges on {d['case']}: "
              f"fieldwork {d['fieldwork']:.6f} vs rapidfuzz {d['rapidfuzz']:.6f}")
