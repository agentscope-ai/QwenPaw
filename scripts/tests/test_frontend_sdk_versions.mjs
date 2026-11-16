import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { test } from "node:test";

const repo = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const dependencies = path.join(repo, "console/node_modules");
async function check(version, source, files = ["author.ts"]) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sdk11-author-version-"));
  const sdk = path.join(root, "node_modules/@qwenpaw/plugin-sdk");
  try {
    fs.cpSync(path.join(repo, "src/qwenpaw/plugins/frontend"), sdk, {
      recursive: true,
    });
    for (const dependency of [
      "typescript",
      "@types/react",
      "@types/prop-types",
      "csstype",
    ]) {
      const target = path.join(root, "node_modules", dependency);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.symlinkSync(path.join(dependencies, dependency), target, "dir");
    }
    const manifest = path.join(root, "plugin.json"),
      project = path.join(root, "tsconfig.json");
    fs.writeFileSync(
      manifest,
      JSON.stringify({ id: "author", version: "0.1.0", sdk: { version } }),
    );
    fs.writeFileSync(
      project,
      JSON.stringify({
        compilerOptions: {
          target: "ES2022",
          module: "ESNext",
          moduleResolution: "bundler",
          skipLibCheck: false,
        },
        files,
      }),
    );
    fs.writeFileSync(path.join(root, "author.ts"), source);
    const { checkProject } = await import(
      pathToFileURL(path.join(sdk, "check.mjs"))
    );
    return checkProject(manifest, project);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

const additions = `
import { getHost as host, forApp, tasks, checkpoints as timeline } from '@qwenpaw/plugin-sdk';
import '@qwenpaw/plugin-sdk/globals';
const composer = host().chat.composer;
const {selectAgent: select} = host().host;
void select('one');
void window.QwenPaw.chat['composer'].read();
void timeline('app').timeline({chatId:'selected'});
const options = {model:{provider_id:'p',model_id:'m'}};
void forApp('app').chat('hello', options);
void tasks('app').start({message:'hello', ...options});
void host().menu.add('app', {id:'menu',label:'Menu'});
void host().route.add('app', {id:'route',path:'/plugin/app',component:()=>null});
void host().harnesses.register('app', {backendId:'example'});
`;

test("SDK 1.0 rejects resolved new symbols, destructuring and model options", async () => {
  const result = await check("1.0.0", additions);
  assert.equal(result.ok, false);
  assert.equal(
    result.findings.filter((f) => f.rule.startsWith("TS")).length,
    0,
    JSON.stringify(result),
  );
  for (const name of [
    "composer",
    "selectAgent",
    "checkpoints",
    "model",
    "menu",
    "route",
    "harnesses",
  ])
    assert.ok(
      result.findings.some(
        (f) => f.rule === "sdk-version" && f.message.startsWith(name + " "),
      ),
      name + JSON.stringify(result),
    );
});

test("SDK 1.1 accepts the same public usage", async () => {
  const result = await check("1.1.0", additions);
  assert.equal(result.ok, true, JSON.stringify(result));
});

test("same-named third-party declarations and old SDK APIs are not rejected", async () => {
  const result = await check(
    "1.0.0",
    `
import { getHost, forApp } from '@qwenpaw/plugin-sdk';
interface ThirdParty { /** @since 9.0.0 */ selectAgent(id:string):void; }
const other: ThirdParty = {selectAgent(id) {}};
other.selectAgent('one');
void getHost().host.getSelectedAgentId();
void forApp('app').chat('hello', {agentId:'one'});
`,
  );
  assert.equal(result.ok, true, JSON.stringify(result));
});

test("invalid methods and parameter types produce compiler diagnostics", async () => {
  const result = await check(
    "1.1.0",
    `
import { getHost } from '@qwenpaw/plugin-sdk';
getHost().chat.composer.replaceAll('x');
getHost().host.selectAgent(42);
`,
  );
  assert.equal(result.ok, false);
  assert.ok(
    result.findings.some(
      (f) =>
        f.rule === "TS2551" &&
        f.message.includes("'replaceAll' does not exist"),
    ),
    JSON.stringify(result),
  );
  assert.ok(result.findings.some((f) => f.rule === "TS2345"));
});

test("an empty author project cannot report success", async () => {
  const result = await check("1.1.0", "export {};", []);
  assert.equal(result.ok, false, JSON.stringify(result));
  assert.equal(result.files.length, 0);
  assert.ok(result.findings.some((f) => f.rule === "input"));
});
