/**
 * Monaco offline setup.
 *
 * By default `@monaco-editor/react` (via `@monaco-editor/loader`) fetches the
 * Monaco core from the jsDelivr CDN at runtime, which breaks the Coding page
 * file preview/editing in offline / air-gapped environments (issue #6261).
 *
 * Here we:
 *   1. Wire `self.MonacoEnvironment.getWorker` to the workers bundled by Vite
 *      (`?worker` imports resolve to local blobs — no network needed).
 *   2. Point the loader at the locally installed `monaco-editor` package so it
 *      never touches the CDN.
 *
 * This module has side effects and must be imported once, before any Monaco
 * editor mounts (see main.tsx).
 */

import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import cssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import htmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import tsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

self.MonacoEnvironment = {
  // Merge instead of overwrite so any MonacoEnvironment fields set elsewhere
  // (e.g. a future CSP / Trusted Types policy) are preserved.
  ...self.MonacoEnvironment,
  getWorker(_workerId: string, label: string) {
    switch (label) {
      case "json":
        return new jsonWorker();
      case "css":
      case "scss":
      case "less":
        return new cssWorker();
      case "html":
      case "handlebars":
      case "razor":
        return new htmlWorker();
      case "typescript":
      case "javascript":
        return new tsWorker();
      default:
        return new editorWorker();
    }
  },
};

// Use the locally bundled monaco instance instead of loading it from the CDN.
loader.config({ monaco });
