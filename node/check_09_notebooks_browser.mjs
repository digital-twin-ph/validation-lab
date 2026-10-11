// Check 09: every notebook runs in the browser kernel, not only in CPython.
//
// The CPython runner (scripts/run_notebooks.py) is necessary and not sufficient: Pyodide
// carries different package versions -- pyproj 3.7.2 against 3.8.0 locally -- so a notebook
// can pass there and fail here. This executes each notebook in the kernel a learner
// actually gets, and fails on any error cell.
//
// Two callers, one operation. In CI this blocks publishing. The same "run everything while
// you have a network" is what a learner needs on the setup visit, because reaching the page
// is already a prerequisite and that is the moment to warm the kernel and find out what
// works. This file is the CI caller; the browser-side one would drive the same commands.
//
// Usage: node check_09_notebooks_browser.mjs [--only NAME] [--timeout SECONDS]
import {createServer} from 'node:http';
import {readFile, readdir} from 'node:fs/promises';
import {extname, join, normalize} from 'node:path';
import {chromium} from 'playwright';

const OUTPUT = new URL('../_output/', import.meta.url).pathname;
const CONTENT = new URL('../content/', import.meta.url).pathname;
const MIME = {'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json',
  '.css':'text/css','.wasm':'application/wasm','.svg':'image/svg+xml','.woff2':'font/woff2','.woff':'font/woff',
  '.ipynb':'application/json','.whl':'application/octet-stream','.map':'application/json','.ttf':'font/ttf',
  '.png':'image/png','.txt':'text/plain','.csv':'text/csv','.tif':'image/tiff'};

const argument = (flag, fallback) => {
  const at = process.argv.indexOf(flag);
  return at === -1 ? fallback : process.argv[at + 1];
};
const only = argument('--only', null);
const perNotebook = Number(argument('--timeout', '900')) * 1000;

/** Serves the built site. No framework: the site is static files and a 404 is a 404. */
async function serve(root) {
  const server = createServer(async (request, response) => {
    try {
      const path = normalize(decodeURIComponent(new URL(request.url, 'http://x').pathname))
        .replace(/^(\.\.[/\\])+/, '');
      let file = join(root, path);
      if (path.endsWith('/')) file = join(file, 'index.html');
      const body = await readFile(file);
      response.writeHead(200, {'content-type': MIME[extname(file)] || 'application/octet-stream'});
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end('not found');
    }
  });
  await new Promise(resolve => server.listen(0, resolve));
  return server;
}

/** The open notebook, once JupyterLite has actually opened it. The widget present a second
 *  after load is not it: an earlier version of this read a transient widget and reported a
 *  five-cell notebook as having one cell. */
const openNotebook = (page, name) => page.waitForFunction(
  expected => {
    const widget = window.jupyterapp?.shell?.currentWidget;
    return widget?.context?.path === expected && (widget.content?.model?.cells?.length ?? 0) > 0;
  }, name, {timeout: 120000});

async function runNotebook(page, origin, name) {
  const started = Date.now();
  await page.goto(`${origin}/lab/index.html?path=${encodeURIComponent(name)}`, {timeout: 120000});
  await page.waitForFunction(() => !!window.jupyterapp, null, {timeout: 120000});
  await openNotebook(page, name);
  // The kernel starts after the notebook opens, and Pyodide downloads on the first one.
  await page.waitForFunction(() => {
    const widget = window.jupyterapp.shell.currentWidget;
    return !!widget?.context?.sessionContext?.session?.kernel;
  }, null, {timeout: perNotebook});

  await page.evaluate(() => window.jupyterapp.commands.execute('notebook:run-all-cells'));

  // Done when every code cell has run **or** one has failed. The second half matters: a
  // raising cell stops the run, so the cells after it never get an execution count, and a
  // condition waiting only for "all executed" waits for something that will never happen.
  // The first version did exactly that and hung for the full fifteen minutes on each of the
  // two notebooks that actually fail -- a runner whose only failure mode is a timeout
  // cannot tell a broken notebook from a slow one.
  await page.waitForFunction(() => {
    const cells = window.jupyterapp.shell.currentWidget.content.model.cells;
    let pending = false;
    for (let index = 0; index < cells.length; index++) {
      const cell = cells.get(index);
      if (cell.type !== 'code') continue;
      const outputs = cell.outputs;
      for (let position = 0; position < (outputs?.length ?? 0); position++)
        if (outputs.get(position).toJSON().output_type === 'error') return true;
      if (!cell.sharedModel.getSource().trim()) continue;
      if (cell.executionCount === null || cell.executionCount === undefined) pending = true;
    }
    return !pending;
  }, null, {timeout: perNotebook, polling: 1000});

  // Errors are read from the cell outputs, as the CPython runner does, rather than from CSS
  // classes: the model is the same thing the notebook saves.
  const errors = await page.evaluate(() => {
    const found = [];
    const cells = window.jupyterapp.shell.currentWidget.content.model.cells;
    for (let index = 0; index < cells.length; index++) {
      const cell = cells.get(index);
      if (cell.type !== 'code') continue;
      const outputs = cell.outputs;
      for (let position = 0; position < (outputs?.length ?? 0); position++) {
        const output = outputs.get(position).toJSON();
        if (output.output_type === 'error')
          found.push({cell: index, ename: output.ename, evalue: String(output.evalue).slice(0, 160)});
      }
    }
    return found;
  });
  return {errors, seconds: (Date.now() - started) / 1000};
}

const server = await serve(OUTPUT);
const origin = `http://localhost:${server.address().port}`;
let notebooks = (await readdir(CONTENT)).filter(name => name.endsWith('.ipynb')).sort();
if (only) notebooks = notebooks.filter(name => name.includes(only));
if (!notebooks.length) {
  console.error('No notebooks found, which is itself a failure.');
  server.close();
  process.exit(1);
}

const browser = await chromium.launch();
// One context for every notebook, so Pyodide and its wheels are downloaded once. That is
// also what a learner's setup visit looks like.
const page = await browser.newPage();
const crashes = [];
page.on('pageerror', error => crashes.push(error.message.slice(0, 160)));

console.log(`Running ${notebooks.length} notebooks in the browser kernel`);
const failed = [];
for (const name of notebooks) {
  try {
    const {errors, seconds} = await runNotebook(page, origin, name);
    const detail = errors.length
      ? `${errors.length} error cell${errors.length === 1 ? '' : 's'}; first at cell ${errors[0].cell}: ${errors[0].ename}: ${errors[0].evalue}`
      : '';
    console.log(`  ${errors.length ? 'FAIL' : 'ok  '} ${name.padEnd(34)} ${seconds.toFixed(1).padStart(6)}s  ${detail}`);
    if (errors.length) failed.push(name);
  } catch (error) {
    console.log(`  FAIL ${name.padEnd(34)}         ${String(error.message).split('\n')[0].slice(0, 160)}`);
    failed.push(name);
  }
}
await browser.close();
server.close();

if (crashes.length) console.log(`  page errors: ${[...new Set(crashes)].join(' | ')}`);
if (failed.length) {
  console.error(`\n${failed.length} of ${notebooks.length} notebooks failed in the browser: ${failed.join(', ')}`);
  process.exit(1);
}
console.log(`\nAll ${notebooks.length} notebooks executed in the browser kernel with no error cells.`);
