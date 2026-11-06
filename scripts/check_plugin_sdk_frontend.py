#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile standalone npm package as an external author in both module modes."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument(
    "--package",
    type=Path,
    required=True,
    help="Standalone package extracted from wheel",
)
parser.add_argument(
    "--dependencies",
    type=Path,
    required=True,
    help="Existing declared npm node_modules",
)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = args.output.resolve()
assert not root.exists(), "Author output must be a new directory"
root.mkdir(parents=True)
environment = {
    **os.environ,
    "npm_config_cache": str(root / "npm-cache"),
    "npm_config_userconfig": str(root / "npmrc"),
}
(root / "package.json").write_text(
    json.dumps({"private": True, "type": "module"}),
)
packed = json.loads(
    subprocess.check_output(
        [
            "npm",
            "pack",
            str(args.package.resolve()),
            "--json",
            "--pack-destination",
            str(root),
        ],
        text=True,
        cwd=root,
        env=environment,
    ),
)[0]
tarball = root / packed["filename"]
subprocess.run(
    [
        "npm",
        "install",
        "--ignore-scripts",
        "--offline",
        "--legacy-peer-deps",
        str(tarball),
    ],
    cwd=root,
    check=True,
    env=environment,
)
for name in ("@types/react", "@types/prop-types", "csstype"):
    shutil.copytree(args.dependencies / name, root / "node_modules" / name)
(root / "author.ts").write_text(
    """
import {
  SDK_VERSION, getHost, forApp, tasks, capabilities,
  type TaskSnapshot, type CancelResult, type PluginRouteDeclaration,
} from "@qwenpaw/plugin-sdk";
import "@qwenpaw/plugin-sdk/globals";
const version: string = SDK_VERSION;
const host = getHost();
const app = forApp("author-app");
const legacyRoute: PluginRouteDeclaration = {
  path: "/plugin/author/legacy", component: () => null, label: "Legacy label",
};
const localizedRoute: PluginRouteDeclaration = {
  path: "/plugin/author/localized", component: () => null,
  label: locale => locale.startsWith("zh") ? "插件" : "Plugin",
  title: locale => locale.startsWith("zh") ? "插件页面" : "Plugin page",
};
host.registerRoutes?.("author", [legacyRoute, localizedRoute]);
async function check() {
  const feature = await capabilities("author-app");
  const task: TaskSnapshot = await tasks("author-app").start({message:"hello"});
  const stopped: CancelResult = await tasks("author-app").cancel(task.run_id);
  return [version, host, app, feature, stopped, window.QwenPaw];
}
async function watch() {
  for await (const update of tasks("author-app").stream("run")) {
    const result: string = update.result;
    const truncated: boolean = update.result_truncated;
    if (update.status === "interrupted") return [result, truncated];
  }
}
void check;
void watch;
""",
)
results = {}
for mode, resolution in (("NodeNext", "NodeNext"), ("ESNext", "bundler")):
    options = {
        "compilerOptions": {
            "target": "ES2022",
            "module": mode,
            "moduleResolution": resolution,
            "strict": True,
            "skipLibCheck": False,
            "noEmit": True,
            "lib": ["ES2022", "DOM"],
        },
        "files": ["author.ts"],
    }
    (root / "tsconfig.json").write_text(json.dumps(options))
    result = subprocess.run(
        [
            "node",
            str((args.dependencies / "typescript/bin/tsc").resolve()),
            "-p",
            str(root / "tsconfig.json"),
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    results[resolution] = {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
(root / "results.json").write_text(json.dumps(results, indent=2))
(root / "runtime.mjs").write_text(
    """
import assert from "node:assert/strict";
import {getHost, capabilities, tasks} from "@qwenpaw/plugin-sdk";
assert.throws(() => getHost(), /unavailable/);
let declaration, requests = [], expectedOptions, failQuery = false, streamClosed = false;
globalThis.window = {QwenPaw: {paw: {forApp(appId) {
  assert.equal(appId, "author-app");
  return {api: {
    async get(path, options) {
      if (expectedOptions) assert.equal(
        options, expectedOptions,
        "capability and task requests must keep scope and AbortSignal",
      );
      if (path === "/.sdk") {
        if (failQuery) throw new Error("offline");
        return declaration;
      }
      requests.push(path);
      return {run_id:"run"};
    },
    async post(path, body, options) {
      if (expectedOptions) assert.equal(options, expectedOptions);
      requests.push([path, body]);
      return {run_id:"run"};
    },
    async *events(path, options) {
      assert.equal(path, "/tasks/run%2Fother/stream");
      assert.deepEqual(options, {...expectedOptions, method:"GET"});
      try { yield {data:JSON.stringify({run_id:"run/other", status:"running"})}; }
      finally { streamClosed = true; }
    }
  }};
}}}};
const api = tasks("author-app");
failQuery = true;
assert.equal((await capabilities("author-app")).status, "unknown");
await assert.rejects(api.start({message:"hello"}), /capability/);
assert.equal(requests.length, 0);
failQuery = false;
for (const value of [
  undefined,
  {sdk_version:"2.0.0", capabilities:["tasks"]},
  {sdk_version:"1.0.0", capabilities:[]},
]) {
  declaration = value;
  await assert.rejects(api.start({message:"hello"}), /capability/);
  assert.equal(requests.length, 0);
}
declaration = {sdk_version:"1.0.0", app_id:"author-app", capabilities:["tasks"]};
assert.equal((await capabilities("author-app")).status, "supported");
await api.start({message:"hello"});
await api.get("run/other");
await api.cancel("run/other");
assert.deepEqual(requests, [
  ["/tasks", {message:"hello"}],
  "/tasks/run%2Fother", ["/tasks/run%2Fother/cancel", {}],
]);
expectedOptions = {
  signal: new AbortController().signal,
  query: {agent_id:"isolated-workspace", session_id:"author-session"},
};
await api.start({message:"scoped", session_id:"author-session"}, expectedOptions);
await api.get("scoped-run", expectedOptions);
await api.cancel("scoped-run", expectedOptions);
const requestCount = requests.length;
const stream = api.stream("run/other", expectedOptions);
assert.deepEqual((await stream.next()).value, {run_id:"run/other", status:"running"});
await stream.return();
assert.equal(streamClosed, true);
assert.equal(requests.length, requestCount, "Disconnect must not cancel the owned task");
console.log("standalone runtime capability gates and encoded task routes passed");
""",
)
runtime = subprocess.run(
    ["node", "runtime.mjs"],
    cwd=root,
    check=False,
    capture_output=True,
    text=True,
)
results["runtime"] = {
    "returncode": runtime.returncode,
    "stdout": runtime.stdout,
    "stderr": runtime.stderr,
}
(root / "results.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
raise SystemExit(any(row["returncode"] for row in results.values()))
