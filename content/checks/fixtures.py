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


def es_number(x) -> str:
    """A number as ECMAScript's Number::toString writes it. Python's repr already gives the shortest digits that
    round-trip, the same digits JavaScript chooses; only where the decimal point goes differs."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    mantissa, _, exp = repr(abs(x)).partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    point = len(whole) + (int(exp) if exp else 0) - (len(whole + frac) - len((whole + frac).lstrip("0")))
    digits = digits.rstrip("0") or "0"
    k, n = len(digits), point
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    return sign + digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))


def _canonical(value) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _canonical(value[k]) for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical(v) for v in value) + "]"
    if isinstance(value, (int, float)):
        return es_number(value)
    return json.dumps(value, ensure_ascii=False)


def canonical_bytes(value) -> bytes:
    """The string Fieldwork's exporter hashes. Arrays keep order; only keys are sorted.

    The canonical form is **ECMAScript's**, because the exporter is JavaScript and `JSON.stringify` has no formatting
    options to bend. Python's `json.dumps` agreed with it everywhere the first fixtures reached but two places, both
    in how a number is written:

    - an exponent is zero-padded in Python and not in JavaScript, `1e-09` against `1e-9`, found on a fixture whose
      tolerance is 1e-9;
    - a number from 1e-6 up to 1e-4 is written with an exponent by Python and in decimal by JavaScript,
      `3.54e-05` against `0.0000354`. Found 2026-11-05 on the first fixture holding satellite column values, in
      mol m-2, which are all in that range.

    The first was patched with a substitution. After the second, numbers are written by `es_number`, which follows
    ECMAScript's Number::toString. Still not RFC 8785 in full, so a third divergence could exist; it would surface
    as a mismatch on export, loud and immediate, not as a fixture quietly passing when it should not.
    """
    return _canonical(value).encode("utf-8")


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
