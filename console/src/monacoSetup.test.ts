/**
 * Unit tests for `src/monacoSetup.ts` - the offline Monaco bootstrap imported
 * for its side effects from `main.tsx` and from
 * `pages/Coding/TabbedEditor.tsx:15` (`import "../../monacoSetup"`).
 *
 * Why this module deserves tests at all: its own header comment records that
 * the default `@monaco-editor/loader` behaviour fetches Monaco from the
 * jsDelivr CDN, which broke the Coding page in offline / air-gapped
 * environments (issue #6261). The three guarantees that fixed it are:
 *
 *   1. `self.MonacoEnvironment.getWorker` resolves every language label to a
 *      *locally bundled* Vite worker (`?worker` imports), never to a CDN URL;
 *   2. unknown labels fall back to the generic editor worker instead of
 *      throwing (so a newly added language cannot silently kill the editor);
 *   3. the loader is pointed at the bundled `monaco` instance.
 *
 * A fourth guarantee is subtler and is spelled out in an inline source
 * comment: the assignment *merges* into any pre-existing `MonacoEnvironment`
 * rather than replacing it, so a future CSP / Trusted Types policy installed
 * elsewhere is preserved. That can only be observed by pre-seeding the global
 * before the import, hence its own describe block.
 *
 * Harness notes:
 *
 * - Every heavy dependency is stubbed (`monaco-editor`, its CSS entry, the
 *   five `?worker` modules, `@monaco-editor/react`, and the RobotFramework
 *   registration). The worker stubs are *distinguishable constructors*, which
 *   is what lets the label-to-worker mapping be asserted instead of merely
 *   "some worker came back".
 * - The module mutates `self.MonacoEnvironment`, so it is re-imported per test
 *   through `vi.resetModules()` to keep the cases independent.
 * - Assertions about what the module *passes on* compare against the module
 *   namespace object obtained from the same registry pass, because
 *   `import * as monaco from "monaco-editor"` yields that namespace, not the
 *   object literal the stub factory returned.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Distinguishable worker constructors. Each stub returns an object tagged with
// its own name so the mapping assertions cannot pass on a shared/default worker.
const workers = vi.hoisted(() => {
  function makeCtor(name: string) {
    const fn = function WorkerCtor() {
      return { workerName: name };
    };
    Object.defineProperty(fn, "name", { value: `${name}Worker` });
    return fn as unknown as new () => { workerName: string };
  }
  return {
    editor: makeCtor("editor"),
    json: makeCtor("json"),
    css: makeCtor("css"),
    html: makeCtor("html"),
    ts: makeCtor("ts"),
    monacoStub: { languages: { register: vi.fn() } },
    loaderConfig: vi.fn(),
    registerRobotFramework: vi.fn(),
  };
});

vi.mock("monaco-editor", () => ({
  default: workers.monacoStub,
  languages: workers.monacoStub.languages,
}));

vi.mock("monaco-editor/min/vs/editor/editor.main.css", () => ({}));

vi.mock("monaco-editor/esm/vs/editor/editor.worker?worker", () => ({
  default: workers.editor,
}));
vi.mock("monaco-editor/esm/vs/language/json/json.worker?worker", () => ({
  default: workers.json,
}));
vi.mock("monaco-editor/esm/vs/language/css/css.worker?worker", () => ({
  default: workers.css,
}));
vi.mock("monaco-editor/esm/vs/language/html/html.worker?worker", () => ({
  default: workers.html,
}));
vi.mock("monaco-editor/esm/vs/language/typescript/ts.worker?worker", () => ({
  default: workers.ts,
}));

vi.mock("@monaco-editor/react", () => ({
  loader: { config: workers.loaderConfig },
}));

vi.mock("./monaco/robotframework", () => ({
  registerRobotFramework: workers.registerRobotFramework,
}));

/**
 * Re-imports the side-effect module against a clean registry and hands back
 * the `monaco-editor` namespace the module will have seen.
 */
async function loadSetup(): Promise<unknown> {
  vi.resetModules();
  const monacoNamespace = await import("monaco-editor");
  await import("./monacoSetup");
  return monacoNamespace;
}

/** The `getWorker` hook installed on the global by the module. */
function getWorker(): (workerId: string, label: string) => unknown {
  const env = (
    self as unknown as { MonacoEnvironment?: Record<string, unknown> }
  ).MonacoEnvironment;
  expect(env).toBeDefined();
  const fn = env?.getWorker as (workerId: string, label: string) => unknown;
  expect(typeof fn).toBe("function");
  return fn;
}

function clearEnv(): void {
  delete (self as unknown as { MonacoEnvironment?: unknown }).MonacoEnvironment;
}

beforeEach(() => {
  vi.clearAllMocks();
  clearEnv();
});

afterEach(() => {
  clearEnv();
});

describe("monacoSetup - worker wiring (issue #6261 offline guarantee)", () => {
  it("installs a getWorker hook on MonacoEnvironment", async () => {
    await loadSetup();

    expect(typeof getWorker()).toBe("function");
  });

  it.each([
    // [label, expected worker stub name]
    ["json", "json"],
    ["css", "css"],
    ["scss", "css"],
    ["less", "css"],
    ["html", "html"],
    ["handlebars", "html"],
    ["razor", "html"],
    ["typescript", "ts"],
    ["javascript", "ts"],
  ])(
    "maps the %s label to its bundled language worker",
    async (label, expected) => {
      await loadSetup();

      const worker = getWorker()("ignored-id", label) as { workerName: string };

      expect(worker.workerName).toBe(expected);
    },
  );

  it.each([["python"], ["markdown"], ["yaml"], [""]])(
    "falls back to the generic editor worker for the unhandled label %s",
    async (label) => {
      await loadSetup();

      const worker = getWorker()("ignored-id", label) as { workerName: string };

      // An unknown language must still yield a usable worker; throwing here is
      // what would take the whole editor down.
      expect(worker.workerName).toBe("editor");
    },
  );

  it("returns a fresh instance per call rather than one shared worker", async () => {
    await loadSetup();
    const hook = getWorker();

    const first = hook("id-a", "json");
    const second = hook("id-b", "json");

    expect(first).not.toBe(second);
  });

  it("ignores the workerId argument when picking a worker", async () => {
    await loadSetup();
    const hook = getWorker();

    // Selection is by language label only; two very different ids must still
    // resolve to the same worker kind.
    const a = hook("vs/editor/editor.worker", "json") as { workerName: string };
    const b = hook("", "json") as { workerName: string };

    expect(a.workerName).toBe(b.workerName);
    expect(a.workerName).toBe("json");
  });
});

describe("monacoSetup - environment merging", () => {
  it("preserves MonacoEnvironment fields set before the import", async () => {
    // Simulates another module having installed a policy hook first, which is
    // the case the source comment calls out (a future CSP / Trusted Types
    // policy). Replacing instead of merging would silently drop it.
    const sentinel = () => null;
    (
      self as unknown as { MonacoEnvironment: Record<string, unknown> }
    ).MonacoEnvironment = { trustedTypesPolicy: sentinel };

    await loadSetup();

    const env = (
      self as unknown as { MonacoEnvironment: Record<string, unknown> }
    ).MonacoEnvironment;
    expect(env.trustedTypesPolicy).toBe(sentinel);
    expect(typeof env.getWorker).toBe("function");
  });

  it("installs getWorker when MonacoEnvironment is absent", async () => {
    await loadSetup();

    expect(typeof getWorker()).toBe("function");
  });
});

describe("monacoSetup - loader and language registration", () => {
  it("points the loader at the bundled monaco instance instead of the CDN", async () => {
    const monacoNamespace = await loadSetup();

    expect(workers.loaderConfig).toHaveBeenCalledTimes(1);
    // The whole point of the module: the loader is configured with a local
    // instance, so no CDN request is ever made.
    expect(workers.loaderConfig).toHaveBeenCalledWith({
      monaco: monacoNamespace,
    });
  });

  it("registers the RobotFramework language exactly once, with monaco", async () => {
    const monacoNamespace = await loadSetup();

    expect(workers.registerRobotFramework).toHaveBeenCalledTimes(1);
    expect(workers.registerRobotFramework).toHaveBeenCalledWith(
      monacoNamespace,
    );
  });
});
