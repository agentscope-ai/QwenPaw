// Sync the Python PEP 440 version from src/qwenpaw/__version__.py into
// console/src-tauri/version/package.json as a SemVer string.
//
// tauri.conf.json already references "version/package.json" as its version
// source, so no modification to tauri.conf.json is required here.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const versionFile = path.join(repoRoot, "src/qwenpaw/__version__.py");
const tauriVersionPackageFile = path.join(
  repoRoot,
  "console/src-tauri/version/package.json",
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

function updateJson(file, update) {
  const data = fs.existsSync(file)
    ? JSON.parse(fs.readFileSync(file, "utf8"))
    : {};
  update(data);
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`);
}

const semver = toSemver(readPythonVersion());

fs.mkdirSync(path.dirname(tauriVersionPackageFile), { recursive: true });
updateJson(tauriVersionPackageFile, (data) => {
  data.version = semver;
});

console.log(`Synced Tauri version to ${semver}`);
