// Sync the Python PEP 440 version from src/qwenpaw/__version__.py into
// console/src-tauri/tauri.conf.json as a SemVer string.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const versionFile = path.join(repoRoot, "src/qwenpaw/__version__.py");
const tauriConfigFile = path.join(
  repoRoot,
  "console/src-tauri/tauri.conf.json",
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

function updateTauriVersion(file, version) {
  const text = fs.readFileSync(file, "utf8");
  const versionPattern = /("version"\s*:\s*)"[^"]+"/;
  if (!versionPattern.test(text)) {
    throw new Error(`Could not update version in ${file}`);
  }

  const nextText = text.replace(versionPattern, `$1"${version}"`);
  if (nextText !== text) {
    fs.writeFileSync(file, nextText);
    return true;
  }
  return false;
}

const semver = toSemver(readPythonVersion());

updateTauriVersion(tauriConfigFile, semver);

console.log(`Synced Tauri version to ${semver}`);
