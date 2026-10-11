"""Loading a fixture and establishing that it is the one it says it is.

Shared because the rule changed on 2026-10-11 and six checks carried their own copy of the
old one. A fixture used to be verified by hashing its bytes against a `.sha256` sidecar.
Both halves of that fail in the browser kernel the lab publishes to:

- the sidecar cannot be read at all — `os.listdir` shows it and `open` raises
  `FileNotFoundError`, and the contents index gives it no mimetype;
- and the bytes are not the file's. JupyterLite serves a `.json` as parsed JSON and the
  kernel reads a re-serialised form: 2,724 bytes on disk arrived as 1,926. A digest over
  the file could never match one taken over what the kernel reads.

So integrity is declared **inside** the fixture and taken over a canonical form: the
fixture with its `integrity` field removed, serialised with object keys sorted, no
whitespace and UTF-8. Fieldwork's exporter computes the same string in JavaScript. This
verifies content rather than bytes, which is weaker in one way — a re-serialised file still
passes — and is the strongest claim this transport permits.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ALGORITHM = "sha256-canonical-json"


def canonical_bytes(value) -> bytes:
    """The string Fieldwork's exporter hashes. Arrays keep order; only keys are sorted.

    The canonical form is **ECMAScript's**, because the exporter is JavaScript and
    `JSON.stringify` has no formatting options to bend. Python agrees with it everywhere but
    one place: an exponent is zero-padded here and not there — `1e-09` against `1e-9` — which
    is what made the first attempt at this disagree on a fixture whose tolerance is 1e-9.
    The substitution below removes that padding.

    This pins one known divergence rather than implementing RFC 8785, so another could
    exist. It would surface as a mismatch on export, which is loud and immediate, not as a
    fixture quietly passing when it should not.
    """
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return re.sub(r"e([+-])0+(\d)", r"e\1\2", text).encode("utf-8")


def canonical_digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_fixture(path: Path) -> tuple[dict, str]:
    """The fixture, and the digest it was verified against.

    Read as text rather than bytes, deliberately: the transport is allowed to re-serialise
    it, and insisting on bytes is what broke the published lab.
    """
    fixture = json.loads(path.read_text(encoding="utf-8"))
    integrity = fixture.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != ALGORITHM:
        raise SystemExit(
            f"{path.name} declares no {ALGORITHM} integrity. Re-export it from Fieldwork: "
            "fixtures verified by a .sha256 sidecar cannot be read in the browser kernel.")
    body = {key: value for key, value in fixture.items() if key != "integrity"}
    found = canonical_digest(body)
    if found != integrity.get("value"):
        raise SystemExit(f"Fixture content mismatch for {path.name}: {found} != {integrity.get('value')}")
    return fixture, found


def verified_asset(fixture: dict, path: Path) -> bytes:
    """A binary file beside the fixture, against the digest the fixture declares for it.

    Bytes are the right test here and they survive: a `.tif` is transferred as base64 and
    arrives unchanged. Only JSON is re-serialised.
    """
    declared = (fixture.get("assets") or {}).get(path.name)
    if not declared:
        raise SystemExit(f"{path.name} is not declared in the fixture's assets, so it cannot be verified.")
    raw = path.read_bytes()
    found = hashlib.sha256(raw).hexdigest()
    if found != declared["sha256"]:
        raise SystemExit(f"Asset hash mismatch for {path.name}: {found} != {declared['sha256']}")
    return raw
