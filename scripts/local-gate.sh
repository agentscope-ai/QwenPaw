#!/bin/bash
# local-gate.sh - Minimal local gate for merge regression prevention.
# Usage: bash scripts/local-gate.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step() {
  local name="$1"
  echo ""
  echo "==> ${name}"
}

step "Sync and branch health check"
bash "$REPO_ROOT/scripts/check-sync-status.sh"

step "Console build"
cd "$REPO_ROOT/console"
npm run -s build
cd "$REPO_ROOT"

step "Backend checks"
if [[ "${LOCAL_GATE_STRICT:-0}" == "1" ]]; then
  echo "Running full backend unit tests (strict mode)..."
  python -m pytest tests/unit/ -q --import-mode=importlib
else
  echo "Running backend smoke checks (set LOCAL_GATE_STRICT=1 for full unit tests)..."
  python - <<'PY'
from src.copaw.app.routers import router

assert router is not None
print("backend smoke checks passed")
PY
fi

step "Knowledge router presence check"
python - <<'PY'
from src.copaw.app.routers import router

paths = {route.path for route in router.routes if hasattr(route, "path")}
if not any("knowledge" in p for p in paths):
    raise SystemExit("knowledge routes are missing")

print("knowledge routes present")
PY

step "i18n missing-key audit"
cd "$REPO_ROOT/console"
node --input-type=module <<'JS'
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const srcRoot = path.join(root, "src");
const localeDir = path.join(srcRoot, "locales");
const localeFiles = ["en.json", "zh.json", "ja.json", "ru.json"];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function getByPath(obj, dottedPath) {
  const parts = dottedPath.split(".");
  let current = obj;
  for (const part of parts) {
    if (current && typeof current === "object" && part in current) {
      current = current[part];
    } else {
      return undefined;
    }
  }
  return current;
}

function walkFiles(dir, exts, out = []) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkFiles(full, exts, out);
      continue;
    }
    if (exts.some((ext) => entry.name.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

const sourceFiles = walkFiles(srcRoot, [".ts", ".tsx"]);
const keyRegexes = [
  /\\bt\\(\\s*["'`]([A-Za-z0-9_.-]+)["'`]\\s*\\)/g,
  /\\bi18n\\.t\\(\\s*["'`]([A-Za-z0-9_.-]+)["'`]\\s*\\)/g,
];

const usedKeys = new Set();
for (const file of sourceFiles) {
  const content = fs.readFileSync(file, "utf8");
  for (const re of keyRegexes) {
    re.lastIndex = 0;
    for (const match of content.matchAll(re)) {
      usedKeys.add(match[1]);
    }
  }
}

const locales = Object.fromEntries(
  localeFiles.map((name) => [name.replace(".json", ""), readJson(path.join(localeDir, name))]),
);

let hasMissing = false;
for (const [lang, data] of Object.entries(locales)) {
  const missing = [];
  for (const key of usedKeys) {
    if (getByPath(data, key) === undefined) {
      missing.push(key);
    }
  }

  if (missing.length > 0) {
    hasMissing = true;
    console.log(`${lang}: missing ${missing.length} keys`);
    for (const key of missing.slice(0, 30)) {
      console.log(`  - ${key}`);
    }
    if (missing.length > 30) {
      console.log(`  ... ${missing.length - 30} more`);
    }
  } else {
    console.log(`${lang}: missing 0 keys`);
  }
}

if (hasMissing) {
  process.exit(1);
}
JS
cd "$REPO_ROOT"

echo ""
echo "local-gate passed"
