import {
  captureChunkDiagnostic,
  failedResourceUrl,
  readBeforeAutomaticReloadDiagnostic,
  recheckChunkResource,
  saveChunkDiagnostic,
} from "../utils/chunkDiagnostics";
import type {
  ChunkDiagnostic,
  ResourceOutcome,
} from "../utils/chunkDiagnostics";
import {
  isChunkLoadError,
  reloadAfterChunkError,
} from "../utils/chunkRecovery";
import { copyText } from "../utils/clipboard";

export interface StartupMessages {
  startup: {
    title: string;
    resource: string;
    runtime: string;
    timeout: string;
  };
  reload: string;
  details: string;
  copy: string;
  copied: string;
  copyFailed: string;
  checking: string;
  recheckNote: string;
  observations: Record<ResourceOutcome, string>;
}

/** Runs inline before entry execution; no React or UI dependency is required. */
export function installStartupMonitor(
  translations: Record<string, StartupMessages>,
): () => void {
  let language = navigator.language;
  try {
    language = localStorage.getItem("language") || language;
  } catch {
    // Startup recovery also works when WebView storage is restricted.
  }
  const locale =
    Object.keys(translations).find(
      (key) => key.toLowerCase() === language.toLowerCase(),
    ) ??
    Object.keys(translations).find(
      (key) => key.split("-")[0] === language.toLowerCase().split("-")[0],
    );
  const messages = translations[locale ?? "en"];
  const startedAt = Date.now();
  let stopped = false;
  let failedPreload: string | null = null;
  let diagnostic: ChunkDiagnostic | null = null;
  let previous: ChunkDiagnostic | null = null;
  let rendered = false;
  let pre: HTMLPreElement;
  let observation: HTMLParagraphElement;
  const placeholder = () => document.querySelector("#root .qwenpaw-boot");
  const diagnosticText = () =>
    JSON.stringify(
      { current: diagnostic, beforeAutomaticReload: previous },
      null,
      2,
    );

  function element<K extends keyof HTMLElementTagNameMap>(tag: K, text = "") {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
  }

  function showFailure() {
    const boot = placeholder();
    const content = boot?.querySelector(".qwenpaw-boot__content");
    if (!content || !diagnostic || rendered) return;
    rendered = true;
    boot!.classList.add("qwenpaw-boot--error");
    const title = element("h1", messages.startup.title);
    const description = element(
      "p",
      messages.startup[diagnostic.startupFailure!],
    );
    const details = element("details");
    details.append(element("summary", messages.details));
    observation = element("p", messages.checking);
    observation.hidden = diagnostic.startupFailure !== "resource";
    pre = element("pre", diagnosticText());
    details.append(observation, element("p", messages.recheckNote), pre);
    const actions = element("div");
    actions.className = "qwenpaw-boot__actions";
    const copy = element("button", messages.copy);
    const reload = element("button", messages.reload);
    copy.type = reload.type = "button";
    reload.className = "qwenpaw-boot__reload";
    reload.addEventListener("click", () => window.location.reload());
    const feedback = element("p");
    feedback.setAttribute("role", "status");
    feedback.hidden = true;
    copy.addEventListener("click", () => {
      void copyText(diagnosticText())
        .then(() => {
          copy.textContent = messages.copied;
          feedback.textContent = messages.copied;
          feedback.hidden = false;
        })
        .catch(() => {
          feedback.textContent = messages.copyFailed;
          feedback.hidden = false;
        });
    });
    actions.append(copy, reload);
    content.replaceChildren(title, description, details, actions, feedback);
  }

  async function fail(
    error: Error,
    kind: NonNullable<ChunkDiagnostic["startupFailure"]>,
    resourceUrl = failedResourceUrl(error),
  ) {
    if (
      stopped ||
      diagnostic ||
      (document.getElementById("root") && !placeholder())
    )
      return;
    clearTimeout(timer);
    diagnostic = {
      ...captureChunkDiagnostic(error, resourceUrl),
      phase: "startup",
      startupFailure: kind,
      elapsedMs: Date.now() - startedAt,
    };
    previous = readBeforeAutomaticReloadDiagnostic(diagnostic.page);
    saveChunkDiagnostic(diagnostic);
    showFailure();
    if (kind !== "resource") return;
    const recheck = await recheckChunkResource(resourceUrl);
    if (stopped) return;
    diagnostic.recheck = recheck;
    saveChunkDiagnostic(diagnostic);
    if (rendered) {
      observation.textContent = messages.observations[recheck.outcome];
      pre.textContent = diagnosticText();
    }
    reloadAfterChunkError(() => {
      diagnostic!.automaticReloadAttempted = true;
      saveChunkDiagnostic(diagnostic!);
    });
  }

  function onError(event: Event) {
    if (event.target instanceof HTMLLinkElement) {
      if (event.target.rel === "modulepreload")
        failedPreload = event.target.href;
      return;
    }
    if (event.target instanceof HTMLScriptElement) {
      if (event.target.type !== "module" || !event.target.src) return;
      const error = new Error(
        `Failed to load entry module: ${event.target.src}`,
      );
      error.name = "ChunkLoadError";
      void fail(error, "resource", failedPreload ?? event.target.src);
    } else if (event instanceof ErrorEvent) {
      const error =
        event.error instanceof Error ? event.error : new Error(event.message);
      void fail(error, "runtime", event.filename || null);
    }
  }

  function onRejection(event: PromiseRejectionEvent) {
    const error =
      event.reason instanceof Error
        ? event.reason
        : new Error(String(event.reason));
    void fail(error, isChunkLoadError(error) ? "resource" : "runtime");
  }

  function stop() {
    stopped = true;
    clearTimeout(timer);
    observer.disconnect();
    window.removeEventListener("error", onError, true);
    window.removeEventListener("unhandledrejection", onRejection);
  }

  const timer = window.setTimeout(() => {
    const error = new Error("Console did not mount within 30000 ms");
    error.name = "StartupTimeoutError";
    void fail(error, "timeout", null);
  }, 30_000);
  const observer = new MutationObserver(() => {
    if (document.getElementById("root") && !placeholder()) stop();
    else if (diagnostic) showFailure();
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  window.addEventListener("error", onError, true);
  window.addEventListener("unhandledrejection", onRejection);
  return stop;
}
