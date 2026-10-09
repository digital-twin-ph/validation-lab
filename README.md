# Fieldwork Validation Lab

Notebooks that **independently recompute** Fieldwork's spatial results in Python
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

## Layout

    content/
      00-kernel-check.ipynb          which packages this kernel really has, and their versions
      01-reproject-vs-pyproj.ipynb   check 01
      02-clip-vs-rasterio.ipynb      check 02
      05-area-vs-geodesic.ipynb      check 05
      checks/                        the Python comparisons, importable and runnable headlessly
    node/                            Node-side checks: the OWL 2 DL reasoner and the SPARQL engine are JS packages
      cq/                            the competency questions, as queries with their expectations
      fixtures/                      an exported run receipt, hash-verified like the Python fixtures
      fixtures/                      exported from Fieldwork, with .sha256 beside each
      results/                       recorded reports, including the environment that produced them

## Running

In a browser, build the static site and open `00-kernel-check.ipynb` first:

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    jupyter lite build --contents content --output-dir _output
    python3 -m http.server --directory _output 8000

Headlessly in CPython, which is faster for iterating but **is not the browser
kernel**:

    pip install -r requirements-checks.txt
    python content/checks/check_01_reproject.py
    python content/checks/check_02_clip.py
    python content/checks/check_05_area.py
    cd node && npm ci && npm run check:all        # ontology reasoning and competency questions

Either way the recorded report names the runtime, so a CPython result is never
mistaken for a Pyodide one.

## Fixtures

Fixtures are produced on the Fieldwork side, which is the direction the boundary
allows. From a Fieldwork checkout:

    node scripts/export-validation-fixture.mjs reproject-utm35s-001 ../validation-lab/content/fixtures
    node scripts/export-validation-fixture.mjs clip-all-touched-001 ../validation-lab/content/fixtures

That writes each fixture, any binary sidecar such as a GeoTIFF, and a `.sha256`
for every file. Regenerate rather than edit: a fixture
edited by hand no longer describes what the application did.

## Results so far

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

Next: polygon area against `pyproj.Geod`, where disagreement is expected because
Fieldwork records a spherical method and `Geod` is ellipsoidal.

## Provisioning, and what that means for offline use

The scientific packages are **not bundled in this site**. The published build
ships four wheels (piplite, ipykernel, pyodide-kernel, widgetsnbextension); the
kernel loads Pyodide **v314.0.6 from a CDN** and the notebooks request
`pyproj`, `shapely`, `rasterio`, `geopandas`, `fiona`, `numpy`, `pandas`, `h3`
and `scipy` from that distribution with `pyodide_js.loadPackage`. Those versions
are the ones the design record names, confirmed against the distribution's own
lock file rather than its documentation.

Two consequences. **The published lab needs network access on first use** of a
notebook, unlike Fieldwork itself, which precaches and reports *Available
offline*. And `piplite.install` is the wrong mechanism for these packages: it
resolves against the site's local wheel index, where they are absent, so it
fails while a `loadPackage` request succeeds. The notebooks used to call
`piplite.install`, which is why `00-kernel-check.ipynb` reported packages as
absent on the published site.

## What a passing check does not establish

That the declared CRS was the right one for a file, that the source coordinates
were recorded correctly, or that the operation suits a public-health question.
Those are separate judgements and stay in Fieldwork's own records.

Licensed under Apache License 2.0, matching Fieldwork.
