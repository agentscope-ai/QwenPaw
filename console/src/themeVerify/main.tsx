/**
 * themeVerify/main.tsx — browser harness for the semantic colour roles.
 *
 * The unit suite can only read the stylesheet text that an override produces.
 * This page mounts a real component tree, applies overrides through the public
 * registry path, and lets a browser read the *computed* colours back, which is
 * the only thing a user actually sees.
 *
 * Driven by `scripts/verify_theme_tokens.py`; not part of the app bundle.
 */
import { createRoot } from "react-dom/client";
import { i18nReady } from "../i18n";
import "../styles/tokens.css";
import { installThemeTokenSync } from "../plugins/themeTokens";
import { installHostExternals } from "../plugins/hostExternals";
import { installHostSdk } from "../plugins/hostSdk/install";
import { chatExtensions } from "../plugins/registry/chatExtensions";
import { setPluginSdkDeclaration } from "../plugins/registry/pluginSdk";
import BackendLoadingPage from "../tauri/BackendLoadingPage";

interface ProbeToken {
  light: string;
  dark: string;
}

interface ThemeProbe {
  /** Registers through the public SDK, exactly as a plugin would. */
  override: (pluginId: string, tokens: Record<string, ProbeToken>) => void;
  /** Public API path, used to prove the SDK gate rejects undeclared plugins. */
  overrideRaw: (
    pluginId: string,
    tokens: Record<string, ProbeToken>,
  ) => unknown;
  /** Disposes the handle the public API returned. */
  dispose: (pluginId: string) => void;
  setScheme: (scheme: "light" | "dark") => void;
  /** Stands in for App.tsx writing the user preset inline on <html>. */
  setPreset: (values: Record<string, string>) => void;
  snapshotKeys: () => string[];
  /** Reads computed colours for one selector, in the current scheme. */
  read: (selector: string) => Record<string, string>;
}

/** One swatch per representative role, so a browser can read it back. */
const SWATCH_TOKENS = [
  "bg",
  "surface",
  "border",
  "text",
  "accent",
  "error-text",
  "success-bg",
  "warning-border",
  "info-text",
];

function readComputed(selector: string): Record<string, string> {
  const element = document.querySelector(selector);
  if (!element) return { missing: selector };
  const style = window.getComputedStyle(element);
  return {
    backgroundColor: style.backgroundColor,
    color: style.color,
    borderTopColor: style.borderTopColor,
  };
}

async function bootstrap(): Promise<void> {
  await i18nReady;
  installHostExternals();
  installHostSdk();
  installThemeTokenSync();

  const root = document.getElementById("root");
  if (!root) throw new Error("theme-verify: missing #root");

  createRoot(root).render(
    <BackendLoadingPage
      status="error"
      elapsed={5}
      totalSec={30}
      errorMessage="probe error"
      onRetry={() => {}}
      showRetry
    />,
  );
  // A plain text node that consumes the same tokens the error card uses.
  const marker = document.createElement("div");
  marker.id = "probe-text";
  marker.style.color = "var(--app-text-secondary)";
  marker.style.borderLeft = "2px solid var(--app-border-strong)";
  marker.textContent = "probe";
  document.body.appendChild(marker);

  // One element per role, each consuming its own custom property, so the
  // computed value proves the override reached a real consumer.
  for (const token of SWATCH_TOKENS) {
    const swatch = document.createElement("div");
    swatch.id = `probe-role-${token}`;
    swatch.style.backgroundColor = `var(--app-${token})`;
    swatch.textContent = token;
    document.body.appendChild(swatch);
  }

  const handles = new Map<string, { dispose: () => void }>();

  const probe: ThemeProbe = {
    override(pluginId, tokens) {
      // The public API is gated on the plugin's declared SDK, so declare it
      // first — that is what the backend sends for a real plugin.
      setPluginSdkDeclaration(pluginId, {
        version: "1.2.0",
        capabilities: ["themeTokens"],
      });
      handles.get(pluginId)?.dispose();
      handles.set(
        pluginId,
        window.QwenPaw.chat!.theme.overrideTokens(
          pluginId,
          tokens as never,
        ) as {
          dispose: () => void;
        },
      );
    },
    dispose(pluginId) {
      handles.get(pluginId)?.dispose();
      handles.delete(pluginId);
    },
    overrideRaw(pluginId, tokens) {
      return window.QwenPaw.chat!.theme.overrideTokens(
        pluginId,
        tokens as never,
      );
    },
    setScheme(scheme) {
      document.documentElement.classList.toggle("dark-mode", scheme === "dark");
    },
    setPreset(values) {
      for (const [name, value] of Object.entries(values)) {
        if (value === "") {
          document.documentElement.style.removeProperty(name);
        } else {
          document.documentElement.style.setProperty(name, value);
        }
      }
    },
    snapshotKeys() {
      return Object.keys(chatExtensions.getThemeTokenSnapshot());
    },
    read: readComputed,
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).__themeProbe = probe;
  document.documentElement.dataset.probeReady = "1";
}

void bootstrap();
