// Sync the Python PEP 440 version from src/qwenpaw/__version__.py into a
// gitignored Tauri config override. Do not write the tracked tauri.conf.json:
// its version would otherwise become a stale generated value after rebases.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const versionFile = path.join(repoRoot, "src/qwenpaw/__version__.py");
const tauriVersionConfigFile = path.join(
  repoRoot,
  "console/src-tauri/tauri.version.conf.json",
);

function readPythonVersion() {
  const text = fs.readFileSync(versionFile, "utf8");
  const match = text.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`Could not read __version__ from ${versionFile}`);
  }
  return match[1];
}

function toSemver(version) {
  const match = version.match(
    /^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?$/,
  );
  if (!match) {
    throw new Error(`Unsupported Python version for Tauri: ${version}`);
  }

  const [, major, minor, patch, prerelease, prereleaseNumber, post, dev] =
    match;
  const prereleaseMap = { a: "alpha", b: "beta", rc: "rc" };
  const labels = [];
  if (prerelease)
    labels.push(`${prereleaseMap[prerelease]}.${prereleaseNumber}`);
  if (post) labels.push(`post.${post}`);
  if (dev) labels.push(`dev.${dev}`);

  return `${major}.${minor}.${patch}${
    labels.length ? `-${labels.join(".")}` : ""
  }`;
}

function writeTauriVersionConfig(file, version) {
  const config = {
    version,
  };
  fs.writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`);
}

const semver = toSemver(readPythonVersion());

writeTauriVersionConfig(tauriVersionConfigFile, semver);

console.log(`Wrote Tauri version override ${semver}`);
