# Fieldwork Validation Lab

Notebooks that **independently recompute** Fieldwork's results in Python
and report agreement or disagreement with a stated tolerance.

The design record lives in the Fieldwork repository, not here:
[`docs/experiments/41-validation-lab.md`](../fieldwork/docs/experiments/41-validation-lab.md).
Findings are written up there too, beside the widget they concern. This
repository holds the notebooks, the fixtures and the machine-readable results.

## The rules that make it worth running

- The lab does not import or re-execute Fieldwork's JavaScript.
- Fieldwork does not call, embed or depend on the lab.
- Neither side shares a numerical module with the other.
- A notebook recomputes from a fixture's `declaredParameters` and `input` only.
  Fieldwork's intermediate values are deliberately absent from fixtures.
- Every fixture is identified by SHA-256 and verified before comparison.
- The tolerance is stated in the notebook before the comparison runs.
- Disagreements are published with both values, never tuned away.

A notebook that reused the implementation under test would measure nothing.

## Where things stand, 26 November 2026

- **51 notebooks**, one per check, plus `00-kernel-check`. Each validates; none teaches. Lessons about what a widget's
  method means live in their own repository, [dive-deeper](https://github.com/digital-twin-ph/dive-deeper), and are
  deferred until the widgets are mature enough to teach from. The older teaching sections that ended some notebooks
  here were taken out on this date.
- **Every check was run again** on fixtures exported from Fieldwork 0.200.0. All agree, except clip raster (02) and
  deduplicate (26), which partly agree as they always have, for the reasons their notebooks give. Four checks still
  run on older fixtures, because nothing can make them again: 18, 25 and the rate ratio in 27 check retired widgets,
  and 50 needs population rasters that are not redistributed.
- **In the browser kernel**, 45 notebooks run. Six run in CPython only and say so when opened in the browser: 26, 33,
  40, 47, 50 and 52 (see below).
- **Both runners fail a check that has regressed**, not only one that raises an error: a notebook that prints
  `agrees: False` where its recorded result agrees.

Fieldwork's record of which widget each check covers, and at which release, is `widgets/parity.json` in the Fieldwork
repository, pinned to a commit of this one.

## Layout

    content/
      00-kernel-check.ipynb   which packages this kernel really has, and their versions
      NN-<what>-vs-<reference>.ipynb
                              one notebook per check: what it checks, how, what should happen, the result, the limits
      checks/                 the Python comparisons, importable and runnable headlessly
      fixtures/               exported from Fieldwork; each carries its own integrity digest
      results/                recorded reports, including the environment that produced them
    node/                     Node-side checks: the OWL 2 DL reasoner and the SPARQL engine are JS packages
      cq/                     the competency questions, as queries with their expectations
      fixtures/               an exported run receipt
    scripts/run_notebooks.py  every notebook in CPython; fails on an error cell or a regressed check

## Running

In a browser, build the static site and open `00-kernel-check.ipynb` first:

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    jupyter lite build --contents content --output-dir _output
    python3 -m http.server --directory _output 8000

Headlessly in CPython, which is faster for iterating but **is not the browser kernel**. A check is a module, run from
`content/`, and writes its result to `content/results/`:

    pip install -r requirements-checks.txt
    cd content && python -m checks.check_06_mean_center
    cd .. && python scripts/run_notebooks.py          # every notebook
    cd node && npm ci && npm run check:all             # ontology reasoning and competency questions
    npm run check:notebooks-browser                    # every notebook in the browser kernel, after the site is built

Either way the recorded report names the runtime, so a CPython result is never mistaken for a Pyodide one.

## Fixtures

Fixtures are produced on the Fieldwork side, which is the direction the boundary allows. From a Fieldwork checkout:

    node scripts/export-validation-fixture.mjs reachability-soho-001 ../validation-lab/content/fixtures

That writes the fixture, with an integrity digest over its canonical form, and any binary file beside it, such as a
GeoTIFF, whose digest the fixture carries. The exporter's usage line lists every fixture it can make. Regenerate rather
than edit: a fixture edited by hand no longer describes what the application did.

## The first results, October 2026

The table below is the record as it stood then, kept for its history. The current results are in `content/results/`.

| Check | Operation | Reference | Result |
| --- | --- | --- | --- |
| 01 | Reproject input, WGS84 UTM 35S to CRS84 | `pyproj` 3.8.0 / PROJ 9.8.1 | **Agrees.** Maximum separation 6.70 × 10⁻⁵ m over 9 points against a 1 mm tolerance |
| 02 | Clip raster, cell centre inside, margin 0 | `rasterio` 1.5.2 / GDAL 3.12.2 | **Agrees exactly.** Same window, same 132 cells, same retained values |
| 02 | Clip raster, all touched, margin 0 | `rasterio` 1.5.2 / GDAL 3.12.2 | **2 of 146 cells differ**, both GDAL-only, after Fieldwork's rule was changed to match. The check found the original 35-cell divergence and then confirmed the fix |
| 02 | Clip raster, all touched, margin 1 | dilation model | **Inconclusive by construction.** `rasterio` has no margin parameter; the 61-cell gap is against a 3 × 3 dilation model, not a validated reference |
| 03 | Ontology structure | own checks over the six `ontology/*.ttl` files | **Clean where checkable.** No fieldwork term is used in a domain, range or subClassOf without being declared. Annotation coverage is partial: 47 of 80 classes carry no label |
| 05 | Calculate area, spherical implementation | independent closed form, same formula | **Agrees.** Relative difference at most 4.8 × 10⁻¹⁴ over 5 boundaries against a 10⁻⁹ criterion |
| 05 | Calculate area, edge model | `pyproj` geodesic on the same sphere | **Reported, not failed.** Boxes differ by under 0.01 %; a mid-latitude triangle with oblique edges differs by **0.30 %** |
| 05 | Calculate area, earth model | `pyproj` geodesic on WGS84 | **Reported.** The declared spherical approximation runs **+0.45 % at the equator to −0.56 % at 60° N**, so the sign changes with latitude and no single factor corrects it |
| 06 | Mean center, UTM projection and unweighted average | `pyproj` 3.8.0 / PROJ 9.8.1 | **Agrees.** Easting exact, northing 9.3 × 10⁻¹⁰ m, returned position 4.1 × 10⁻¹⁰ m ground separation, against a 1 mm criterion |
| 04 | Competency questions, relevance | SPARQL over an exported run receipt, compared with the documented statuses | **12 of 13 expectations met, 4 of 4 refusals held, 1 drift found.** The reporting boundary is not typed `fw:StudyArea` in the Old Naledi receipt, so it cannot be found by its role |
| 03 | Ontology meaning | Konclude OWL 2 DL | **Consistent, but unfalsifiably so.** Zero disjointness, cardinality or restriction axioms, and classification infers no subsumption beyond those asserted. A probe conflating terms the audit says must stay distinct stays consistent; adding three `owl:disjointWith` axioms makes it inconsistent |

Both checks ran in CPython 3.13.3 on macOS arm64, **not** in Pyodide, so the
first acceptance criterion in the design record is unmet for a browser kernel
and these figures should be reproduced there.

Check 01's residual is explained: Fieldwork stores coordinates rounded to nine
decimal places, whose worst case is about 7.8 × 10⁻⁵ m at the fixture's
latitudes, above the observed separation. The agreement is limited by the
documented rounding, not by the projection.

Check 02 is the clearest case of the lab working. It found a 35-cell divergence
in all-touched clipping, which was attributed to two specific lines of Fieldwork's
own code: an inclusion test measuring distance to a **closed** cell rectangle, and
a fractional window pad. Fieldwork changed the rule to positive-area coverage,
and this check confirmed the result — 2 differing cells instead of 35, with the
cropped window now agreeing. Those 2 are GDAL-only and come from its line
rasterizer burning cells at an exactly aligned cutline vertex, an artifact rather
than a stateable rule, so they are recorded rather than chased. The write-up is in
the Fieldwork repository at `docs/experiments/29-raster-edge-inclusion.md`.

Check 07 compares `reachable_nodes` against NetworkX, which is the reference the
original case study itself used. The reached sets agree exactly over 738
junctions and the costs agree to 5 mm, which is the rounding Fieldwork applies
to the number it publishes. The notebook also shows how far the answer travels
with its assumption: the same graph and origin reach 69 junctions at 3 km/h and
246 at 6 km/h, against 142 at the case study's 4.5 km/h.

Check 08 compares `reachable_corridor` against Shapely, rebuilding the corridor
from the widget's stated rule with GEOS rather than comparing geometry feature
by feature. The street selection agrees exactly — 301 streets entered, 45 cut
part-way — and the areas differ by 0.116%, which is two geometry engines
approximating a 25 m radius in two different projections. The notebook also
shows the corridor's area halving at a 10 m half-width and rising half again at
60 m, against a figure the case study records no reason for.

Next: a reference for the travel time bands, where NetworkX has no equivalent
operation, so the comparison would have to be against plain arithmetic.

## Provisioning, and what that means for offline use

The scientific packages are **not bundled in this site**. The published build
ships four wheels (piplite, ipykernel, pyodide-kernel, widgetsnbextension); the
kernel loads Pyodide **v314.0.6 from a CDN** and each notebook requests what it
imports from that distribution with `pyodide_js.loadPackage`. Those versions are
the ones the design record names, confirmed against the distribution's own lock
file rather than its documentation.

**Each notebook requests what it imports, and that is a requirement, not a
preference.** Requesting `pyproj` alongside `rasterio` makes `rasterio.open`
crash this kernel outright — `RuntimeError: null function` in the GDAL wasm
module, fatal, with no error cell to show for it. `00-kernel-check.ipynb` carries
the measured map of which combinations survive and states plainly that the
mechanism is unexplained. A notebook that loads the whole set "to be safe" is the
one that fails.

Two consequences. **The published lab needs network access on first use** of a
notebook, unlike Fieldwork itself, which precaches and reports *Available
offline*. And `piplite.install` is the wrong mechanism for these packages: it
resolves against the site's local wheel index, where they are absent, so it
fails while a `loadPackage` request succeeds. The notebooks used to call
`piplite.install`, which is why `00-kernel-check.ipynb` reported packages as
absent on the published site.

## Getting the notebooks to run in the browser kernel, October 2026

**Fixed 2026-10-11.** Integrity moved from a `.sha256` sidecar over the file's bytes to an
`integrity` field inside the fixture, taken over a canonical form — the fixture with that
field removed, object keys sorted, no whitespace, UTF-8. Fieldwork's exporter computes the
same string in JavaScript and writes no sidecars. `01-reproject-vs-pyproj`, the notebook
reported as broken, now passes in the browser kernel, and all seven pass in CPython.

One cost worth knowing: the canonical form has to be byte-identical in two languages and
was not. The exporter wrote `1e-9` where Python produced `1e-09`. The canonical form is now
defined as ECMAScript's and Python normalises its exponents to match. That pins one known
divergence rather than implementing RFC 8785, and another would surface as a loud mismatch
at export rather than as a fixture quietly passing.

**And `02-clip-vs-rasterio` is fixed too, later the same day.** It had run for more than
twelve minutes without finishing, where it takes 1.0 second in CPython, and the apparent
timeout was two defects wearing one symptom.

`rasterio.open` **crashes this kernel** when `pyproj` has been requested alongside it:
`RuntimeError: null function` inside the GDAL wasm module, fatal, killing the kernel rather
than raising. The notebook asked for all nine packages because a `piplite` fix on
2026-10-08 copied one list into every notebook. It now asks for the four it imports and
passes in 12 seconds. `00-kernel-check.ipynb` carries the measured map of which
combinations survive, and says that the mechanism is unexplained.

**A fatal kernel error produces no error cell**, so the runner was waiting for an execution
count that could never arrive, and reported a timeout — which says nothing about the cause,
when the kernel had died within seconds. It now watches the console and page errors for a
fatal and fails in seconds with the message. A check whose only failure mode is a timeout
cannot tell a crash from slow work.

All seven notebooks now execute in the browser kernel in under a minute, and the check
**blocks publication** as of 2026-10-11.

### What the original failure was



Found 2026-10-11 by executing them in the browser kernel for the first time
(`node/check_09_notebooks_browser.mjs`). **Six of the seven fail**, every one at
the same line, while all seven pass in CPython in eight seconds.

Two defects, and the second survives any fix to the first.

**The digest sidecars cannot be read.** `open('/drive/fixtures/x.json.sha256')`
raises `FileNotFoundError` although `os.listdir` shows the file. The contents
index gives it `mimetype: null`, where the fixture beside it gets
`application/json`. Renaming one to `.sha256.txt` — which the index then typed
`text/plain` — did not fix it, so the cause is not only the extension and is not
yet established.

**And byte-identity digests cannot work through this transport at all.** The
fixture is 2,724 bytes on disk and the kernel reads **1,926**: JupyterLite
serves a `.json` as parsed JSON and the driver re-serialises it. The content is
the same and the bytes are not, so `sha256(raw)` cannot match a digest taken
over the file. The check's own identity rule — "the notebook records the
fixture's hash and fails if it does not match" — is unsatisfiable in a browser
as written.

The honest options are to digest a **canonical form** of the JSON rather than
its bytes, computed the same way by Fieldwork's exporter and the check, or to
carry fixtures in a format the transport does not rewrite. Both change the
fixture contract across repositories, so neither is done here.

## Notebooks that run in CPython only

Each says so when opened in the browser, with its reason, and skips its later cells rather than failing.

| Notebook | Why not in the browser kernel |
| --- | --- |
| 26 Deduplicate | Its two references, rapidfuzz and jellyfish, are not in the Pyodide distribution |
| 33 Regression | The New York case reads its data from Zenodo by HTTP range requests, which the kernel cannot make |
| 40 Relate, allowing for spelling | rapidfuzz's score is the criterion, and rapidfuzz is not there |
| 47, 52 QR codes | OpenCV, the decoder every code is read with, is not there |
| 50 Population models | Its rasters are tens of megabytes each and not redistributed |

**Found 2026-11-09 for 26 and 40.** Neither rapidfuzz nor jellyfish publishes a pure-Python wheel `piplite` could use.
A Jaro-Winkler written in the lab would run, but it would be one more hand-written implementation set against
Fieldwork's rather than one by other authors, which is what the two libraries are there for.

Checks 49 and 51 do run there: they read their source files from GitHub at the pinned commit when the example is not
checked out beside this repository.

## What a passing check does not establish

That the declared CRS was the right one for a file, that the source coordinates
were recorded correctly, or that the operation suits a public-health question.
Those are separate judgements and stay in Fieldwork's own records.

Licensed under Apache License 2.0, matching Fieldwork.
