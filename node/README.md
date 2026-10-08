# Node-side checks

The OWL 2 DL reasoner is a JavaScript and WebAssembly package, so these checks
live here rather than in the Python notebooks. The boundary rules in the root
README apply unchanged: nothing here imports Fieldwork code, and every check
reads the ontology files as data.

    npm ci
    npm run check:ontology          # writes results/check-03-ontology.json

`rdf-reasoner-konclude` is **LGPL-3.0-or-later** and about 25 MB unpacked
because it bundles a Konclude WebAssembly build. It is deliberately a dependency
of this lab and **not** of Fieldwork, whose browser bundle is Apache-2.0 and
whose asset manifest is explicit. Keep it that way: a reasoner in the
application bundle would be a licensing and size decision of its own.

It is the same engine [Ontosphere](https://github.com/ThHanke/ontosphere) uses
in the browser, so a verdict here should match what that tool reports
interactively on the same files.
