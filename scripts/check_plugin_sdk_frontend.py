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
for name in ("@types/react", "@types/prop-types", "csstype", "typescript"):
    shutil.copytree(args.dependencies / name, root / "node_modules" / name)
(root / "author.ts").write_text(
    """
import {
  SDK_VERSION, getHost, forApp, tasks, capabilities, checkpoints,
  type TaskSnapshot, type CancelResult, type PluginRouteDeclaration,
  type HarnessSettingsProps, type HarnessFrontendExtension,
} from "@qwenpaw/plugin-sdk";
import "@qwenpaw/plugin-sdk/globals";
const version: string = SDK_VERSION;
const host = getHost();
const harness: HarnessFrontendExtension = {
  backendId: "author-backend",
  SettingsComponent: (props: HarnessSettingsProps) => {
    props.onChange({...props.value, model: "selected"});
    return null;
  },
};
host.harnesses.register("author", harness).dispose();
window.QwenPaw.harnesses.register("author", harness).dispose();
const app = forApp("author-app");
const draft = host.chat.composer.read();
if (draft) {
  host.chat.composer.replace(draft, "Improved prompt");
  // @ts-expect-error Draft snapshots are readonly.
  draft.text = "other";
}
// @ts-expect-error No arbitrary session reader exists on the composer.
host.chat.composer.read("other-session");
// @ts-expect-error Unknown methods must be rejected.
host.chat.composer.replaceAll("text");
// @ts-expect-error Workspace IDs are strings.
void host.host.selectAgent(42);
const model = { provider_id: "provider", model_id: "model" };
// @ts-expect-error PawApp chats use the Agent's configured model.
void app.chat("hello", { model });
// @ts-expect-error PawApp tasks use the Agent's configured model.
void tasks("author-app").start({ message: "hello", model });
// @ts-expect-error Restore requires an explicitly selected conversation.
void checkpoints("author-app").restore("checkpoint", { agentId: "default" });
// @ts-expect-error Selected files are paths.
void checkpoints("author-app").previewRestore("checkpoint", { agentId: "default", chatId: "chat", files: true });
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
(root / "author.ts").write_text(
    """
import {getHost, checkpoints} from "@qwenpaw/plugin-sdk";
const host = getHost();
const draft = host.chat.composer.read();
if (draft) host.chat.composer.replace(draft, "Improved");
void host.host.selectAgent("default");
void host.chat.composer.model();
void checkpoints("author-app").timeline({agentId: "default", chatId: "selected"});
""",
)
for minimum, expected in (("1.0.0", 1), ("1.1.0", 1), ("1.2.0", 0)):
    (root / "plugin.json").write_text(
        json.dumps(
            {"id": "author", "version": "0.1.0", "sdk": {"version": minimum}},
        ),
    )
    result = subprocess.run(
        [
            str(root / "node_modules/.bin/qwenpaw-sdk-check"),
            "plugin.json",
            "tsconfig.json",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip(), (
        result.returncode,
        result.stdout,
        result.stderr,
    )
    report = json.loads(result.stdout)
    matched = result.returncode == expected and (
        report["ok"]
        if expected == 0
        else len([f for f in report["findings"] if f["rule"] == "sdk-version"])
        >= 6
    )
    results[f"minimum-{minimum}"] = {
        "returncode": 0 if matched else 1,
        "checker_exit_code": result.returncode,
        "report": report,
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
