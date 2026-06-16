/**
 * Architecture Viewer - Local HTTP server
 * Run from workspace root: node /skills/arch-viewer/scripts/serve.js
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const { execSync } = require('child_process');

const PORT = process.env.ARCH_VIEWER_PORT ? parseInt(process.env.ARCH_VIEWER_PORT) : 7432;

// Auto-detect workspace root: walk up from __dirname looking for directory
// serve.js lives at <root>/skills/arch-viewer/scripts/serve.js
function findRoot() {
  if (process.env.ARCH_VIEWER_ROOT) return process.env.ARCH_VIEWER_ROOT;
  let dir = __dirname;
  const MAX_DEPTH = 10;
  for (let i = 0; i < MAX_DEPTH; i++) {
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
    if (fs.existsSync(path.join(dir, '.cursor', 'argoschema'))) return dir;
    if (fs.existsSync(path.join(dir, 'package.json')) && fs.existsSync(path.join(dir, '.cursor'))) return dir;
  }
  return process.cwd();
}

const ROOT = findRoot();

const PATHS = {
  data:   path.join(ROOT, 'design', 'KG', 'SystemArchitecture.json'),
  schema: path.join(ROOT, '.cursor', 'argoschema', 'SystemArchitecture.schema.json'),
  html:   path.join(__dirname, '..', 'assets', 'index.html'),
  assets: path.join(__dirname, '..', 'assets'),
};

const MIME_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

function respond(res, status, contentType, body) {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
  });
  res.end(body);
}

function readFile(filePath) {
  try { return { ok: true, content: fs.readFileSync(filePath, 'utf-8') }; }
  catch (e) { return { ok: false, error: e.message }; }
}

function readAsset(requestPath) {
  const relativePath = decodeURIComponent(requestPath.replace(/^\/assets\//, ''));
  const absolutePath = path.resolve(PATHS.assets, relativePath);
  const assetRoot = path.resolve(PATHS.assets);
  if (!absolutePath.startsWith(assetRoot)) {
    return { ok: false, status: 403, error: 'Forbidden' };
  }
  try {
    return {
      ok: true,
      content: fs.readFileSync(absolutePath),
      contentType: MIME_TYPES[path.extname(absolutePath).toLowerCase()] || 'application/octet-stream',
    };
  } catch (e) {
    return { ok: false, status: 404, error: e.message };
  }
}

function emptyChangeSummary() {
  return {
    views: { new: [], modified: [], deleted: [] },
    elements: { new: [], modified: [], deleted: [] },
    relationships: { new: [], modified: [], deleted: [] },
    deletedObjects: {
      views: [],
      elements: [],
      relationships: [],
    },
    deletedViewMembership: {
      elements: {},
      relationships: {},
    },
  };
}

function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function indexById(items, idField) {
  const map = new Map();
  for (const item of items || []) {
    const id = item?.[idField];
    if (id !== undefined && id !== null) {
      map.set(String(id), item);
    }
  }
  return map;
}

function diffEntityList(currentItems, baseItems, idField) {
  const currentById = indexById(currentItems, idField);
  const baseById = indexById(baseItems, idField);
  const added = [];
  const modified = [];
  const deleted = [];

  for (const [id, currentItem] of currentById.entries()) {
    const baseItem = baseById.get(id);
    if (!baseItem) {
      added.push(id);
      continue;
    }
    if (stableStringify(currentItem) !== stableStringify(baseItem)) {
      modified.push(id);
    }
  }

  for (const id of baseById.keys()) {
    if (!currentById.has(id)) {
      deleted.push(id);
    }
  }

  return {
    new: added,
    modified,
    deleted,
  };
}

function pickByIds(items, idField, ids) {
  const idSet = new Set((ids || []).map((id) => String(id)));
  if (idSet.size === 0) {
    return [];
  }
  return (items || []).filter((item) => idSet.has(String(item?.[idField])));
}

function toUniqueArray(values) {
  return [...new Set((values || []).map((value) => String(value)))];
}

function buildDeletedMembership(headGraph, summary) {
  const deletedElementSet = new Set((summary.elements.deleted || []).map((id) => String(id)));
  const deletedRelationshipSet = new Set((summary.relationships.deleted || []).map((id) => String(id)));
  const elementByView = {};
  const relationshipByView = {};

  for (const view of headGraph.views || []) {
    const viewId = String(view.view_id);
    const deletedElements = (view.included_elements || []).filter((id) => deletedElementSet.has(String(id))).map((id) => String(id));
    const deletedRelationships = (view.included_relationships || []).filter((id) => deletedRelationshipSet.has(String(id))).map((id) => String(id));
    if (deletedElements.length > 0) {
      elementByView[viewId] = toUniqueArray(deletedElements);
    }
    if (deletedRelationships.length > 0) {
      relationshipByView[viewId] = toUniqueArray(deletedRelationships);
    }
  }

  return {
    elements: elementByView,
    relationships: relationshipByView,
  };
}

function getRelativePosixPath(filePath) {
  return path.relative(ROOT, filePath).split(path.sep).join('/');
}

function readHeadFileText(relativePath) {
  const escaped = relativePath.replace(/"/g, '\\"');
  try {
    return execSync(`git show HEAD:${escaped}`, {
      cwd: ROOT,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
    });
  } catch (_error) {
    return null;
  }
}

function computeChangeSummary() {
  const summary = emptyChangeSummary();
  const currentText = readFile(PATHS.data);
  if (!currentText.ok) {
    return summary;
  }

  let currentGraph;
  try {
    currentGraph = JSON.parse(currentText.content);
  } catch (_error) {
    return summary;
  }

  const relativeDataPath = getRelativePosixPath(PATHS.data);
  const headText = readHeadFileText(relativeDataPath);
  if (!headText) {
    // File does not exist in HEAD (new file or repo state unavailable): treat all as new.
    summary.views.new = (currentGraph.views || []).map((view) => String(view.view_id)).filter(Boolean);
    summary.elements.new = (currentGraph.elements || []).map((element) => String(element.id)).filter(Boolean);
    summary.relationships.new = (currentGraph.relationships || []).map((relationship) => String(relationship.id)).filter(Boolean);
    return summary;
  }

  let headGraph;
  try {
    headGraph = JSON.parse(headText);
  } catch (_error) {
    return summary;
  }

  summary.views = diffEntityList(currentGraph.views || [], headGraph.views || [], 'view_id');
  summary.elements = diffEntityList(currentGraph.elements || [], headGraph.elements || [], 'id');
  summary.relationships = diffEntityList(currentGraph.relationships || [], headGraph.relationships || [], 'id');
  summary.deletedObjects.views = pickByIds(headGraph.views || [], 'view_id', summary.views.deleted);
  summary.deletedObjects.elements = pickByIds(headGraph.elements || [], 'id', summary.elements.deleted);
  summary.deletedObjects.relationships = pickByIds(headGraph.relationships || [], 'id', summary.relationships.deleted);
  summary.deletedViewMembership = buildDeletedMembership(headGraph, summary);
  return summary;
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, PUT, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (url.pathname === '/api/schema') {
    const { ok, content, error } = readFile(PATHS.schema);
    if (ok) respond(res, 200, 'application/json', content);
    else respond(res, 404, 'application/json', JSON.stringify({ error }));

  } else if (url.pathname === '/api/data') {
    if (req.method === 'GET') {
      const { ok, content, error } = readFile(PATHS.data);
      if (ok) respond(res, 200, 'application/json', content);
      else respond(res, 404, 'application/json', JSON.stringify({ error }));

    } else if (req.method === 'PUT') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        try {
          JSON.parse(body); // validate JSON
          fs.writeFileSync(PATHS.data, body, 'utf-8');
          respond(res, 200, 'application/json', JSON.stringify({ ok: true }));
        } catch (e) {
          respond(res, 400, 'application/json', JSON.stringify({ error: e.message }));
        }
      });
    } else {
      respond(res, 405, 'application/json', JSON.stringify({ error: 'Method not allowed' }));
    }

  } else if (url.pathname === '/api/changes') {
    if (req.method !== 'GET') {
      respond(res, 405, 'application/json', JSON.stringify({ error: 'Method not allowed' }));
      return;
    }

    const summary = computeChangeSummary();
    respond(res, 200, 'application/json', JSON.stringify(summary));

  } else if (url.pathname === '/' || url.pathname === '/index.html') {
    const { ok, content, error } = readFile(PATHS.html);
    if (ok) respond(res, 200, 'text/html; charset=utf-8', content);
    else respond(res, 500, 'text/plain', `Error reading viewer: ${error}`);

  } else if (url.pathname.startsWith('/assets/')) {
    const asset = readAsset(url.pathname);
    if (asset.ok) respond(res, 200, asset.contentType, asset.content);
    else respond(res, asset.status || 404, 'application/json', JSON.stringify({ error: asset.error }));

  } else {
    respond(res, 404, 'text/plain', 'Not found');
  }
});

server.listen(PORT, '127.0.0.1', () => {
  const url = `http://localhost:${PORT}`;
  console.log(`\n  Architecture Viewer  →  ${url}`);
  console.log(`  Data   : ${PATHS.data}`);
  console.log(`  Schema : ${PATHS.schema}`);
  console.log('\n  Press Ctrl+C to stop.\n');

  const openCmd =
    process.platform === 'win32' ? `start "" "${url}"` :
    process.platform === 'darwin' ? `open "${url}"` : `xdg-open "${url}"`;
  exec(openCmd);
});

server.on('error', err => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Port ${PORT} is already in use. Set ARCH_VIEWER_PORT to use a different port.`);
  } else {
    console.error('Server error:', err.message);
  }
  process.exit(1);
});
