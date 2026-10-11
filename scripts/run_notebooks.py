"""Execute every notebook and fail on any error cell.

The notebooks are the instrument that checks Fieldwork's computations, and until
2026-10-11 nothing executed them: they were run as a set for the first time by hand, and
the published site had been built from notebooks nobody had run. A check that is never run
is a claim, not a check.

Two callers, deliberately one mechanism:

- **CI**, where a non-zero exit fails the build.
- **A learner's setup visit**, where the same "run everything and report what worked" warms
  the kernel and surfaces failures while there is still a network to fix them with. That
  caller runs in the browser and is not this file, but the contract it reports against is
  the one defined here.

This runs under CPython. A notebook can pass here and fail in Pyodide, because the package
versions differ -- pyproj 3.8.0 here against 3.7.2 in the distribution the kernel loads --
so passing is necessary and not sufficient. The environment is recorded in the output for
that reason.
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

CONTENT = Path(__file__).resolve().parent.parent / "content"


def failing_cells(notebook) -> list[tuple[int, str]]:
    """Cells whose output records an error, which nbclient does not raise for when a
    notebook declares it tolerates errors. Checked directly so a tolerated error is still
    reported: this check exists to find them, not to honour a notebook's opinion of them."""
    found = []
    for index, cell in enumerate(notebook.cells):
        for output in cell.get("outputs", []):
            if output.get("output_type") == "error":
                found.append((index, f"{output.get('ename','error')}: {output.get('evalue','')}"))
    return found


def run(path: Path, timeout: int) -> tuple[bool, str, float]:
    started = time.monotonic()
    notebook = nbformat.read(path, as_version=4)
    client = NotebookClient(
        notebook, timeout=timeout, kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
        allow_errors=True,   # collect every failure rather than stopping at the first
    )
    try:
        client.execute()
    except CellExecutionError as error:                      # pragma: no cover - defensive
        return False, f"execution stopped: {error}".split("\n")[0][:200], time.monotonic() - started
    except Exception as error:                               # a kernel that will not start
        return False, f"{type(error).__name__}: {error}".split("\n")[0][:200], time.monotonic() - started
    failures = failing_cells(notebook)
    if failures:
        first = failures[0]
        detail = f"{len(failures)} error cell{'' if len(failures) == 1 else 's'}; first at cell {first[0]}: {first[1][:160]}"
        return False, detail, time.monotonic() - started
    return True, "", time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per notebook")
    parser.add_argument("--only", help="run one notebook by name")
    arguments = parser.parse_args()

    notebooks = sorted(CONTENT.glob("*.ipynb"))
    if arguments.only:
        notebooks = [n for n in notebooks if arguments.only in n.name]
    if not notebooks:
        print("No notebooks found, which is itself a failure.", file=sys.stderr)
        return 1

    print(f"Running {len(notebooks)} notebooks under "
          f"{platform.python_implementation()} {platform.python_version()}")
    failed = []
    for path in notebooks:
        ok, detail, seconds = run(path, arguments.timeout)
        print(f"  {'ok  ' if ok else 'FAIL'} {path.name:<34} {seconds:6.1f}s  {detail}")
        if not ok:
            failed.append(path.name)
    if failed:
        print(f"\n{len(failed)} of {len(notebooks)} notebooks failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    print(f"\nAll {len(notebooks)} notebooks executed with no error cells.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
