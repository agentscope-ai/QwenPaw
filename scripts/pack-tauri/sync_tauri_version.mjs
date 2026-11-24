// Sync the Python PEP 440 version from src/qwenpaw/__version__.py into a
// gitignored Tauri config override. Do not write the tracked tauri.conf.json:
// its version would otherwise become a stale generated value after rebases.
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
  if (dev) labels.push(`dev.${dev}`);

  const prereleaseSuffix = labels.length ? `-${labels.join(".")}` : "";
  const postMetadata = post ? `+post.${post}` : "";
  return `${major}.${minor}.${patch}${prereleaseSuffix}${postMetadata}`;
}

function readBaseUpdaterConfig() {
  const config = JSON.parse(fs.readFileSync(tauriConfigFile, "utf8"));
  const updater = config?.plugins?.updater ?? {};
  if (!updater.pubkey) {
    throw new Error(
      `Could not read plugins.updater.pubkey from ${tauriConfigFile}`,
    );
  }
  return updater;
}

function readUpdaterEndpoints(baseUpdater) {
  const raw = process.env.TAURI_UPDATER_ENDPOINTS?.trim();
  if (!raw) return baseUpdater.endpoints;

  if (raw.startsWith("[")) {
    const parsed = JSON.parse(raw);
    if (
      !Array.isArray(parsed) ||
      parsed.some((entry) => typeof entry !== "string")
    ) {
      throw new Error(
        "TAURI_UPDATER_ENDPOINTS JSON must be an array of strings",
      );
    }
    return parsed;
  }

  return raw
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function shouldCreateUpdaterArtifacts() {
  return Boolean(process.env.TAURI_SIGNING_PRIVATE_KEY?.trim());
}

function writeTauriVersionConfig(file, version) {
  const baseUpdater = readBaseUpdaterConfig();
  const pubkey = process.env.TAURI_UPDATER_PUBKEY?.trim() || baseUpdater.pubkey;
  const endpoints = readUpdaterEndpoints(baseUpdater);
  const createUpdaterArtifacts = shouldCreateUpdaterArtifacts();
  const config = {
    version,
    ...(createUpdaterArtifacts
      ? {
          bundle: {
            createUpdaterArtifacts: true,
          },
        }
      : {}),
    plugins: {
      updater: {
        pubkey,
        ...(endpoints?.length ? { endpoints } : {}),
      },
    },
  };
  fs.writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`);
  console.log(
    `Using updater pubkey from ${
      process.env.TAURI_UPDATER_PUBKEY?.trim()
        ? "TAURI_UPDATER_PUBKEY"
        : "tauri.conf.json"
    }`,
  );
  if (process.env.TAURI_UPDATER_ENDPOINTS?.trim()) {
    console.log("Using updater endpoints from TAURI_UPDATER_ENDPOINTS");
  }
  console.log(
    createUpdaterArtifacts
      ? "Creating Tauri updater artifacts"
      : "Skipping Tauri updater artifacts because TAURI_SIGNING_PRIVATE_KEY is not set",
  );
}

const semver = toSemver(readPythonVersion());

writeTauriVersionConfig(tauriVersionConfigFile, semver);

console.log(`Wrote Tauri version override ${semver}`);
