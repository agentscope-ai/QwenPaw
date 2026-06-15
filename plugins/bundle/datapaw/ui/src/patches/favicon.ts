import { DATAPAW_AGENT_ID, PLUGIN_ID } from "../lib/constants";
import { getSelectedAgentId } from "../lib/agent";

const DATAPAW_FAVICON_PATH = `/frontend_plugin/${PLUGIN_ID}/files/favicon.ico`;
const DEFAULT_FAVICON_HREF = "/online.svg";
const SYNC_INTERVAL_MS = 500;

let installed = false;
let timer: number | null = null;
let lastIsDatapaw: boolean | null = null;
let managedLink: HTMLLinkElement | null = null;
let originalFavicon:
  | {
      href: string;
      rel: string;
      type: string | null;
      sizes: string | null;
    }
  | null = null;

function findFaviconLink(): HTMLLinkElement | null {
  return document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
}

function ensureFaviconLink(): HTMLLinkElement {
  const existing = findFaviconLink();
  if (existing) return existing;

  const link = document.createElement("link");
  link.rel = "icon";
  link.href = DEFAULT_FAVICON_HREF;
  document.head.appendChild(link);
  return link;
}

function captureOriginalFavicon(link: HTMLLinkElement): void {
  if (originalFavicon) return;
  originalFavicon = {
    href: link.getAttribute("href") || DEFAULT_FAVICON_HREF,
    rel: link.getAttribute("rel") || "icon",
    type: link.getAttribute("type"),
    sizes: link.getAttribute("sizes"),
  };
}

function setOptionalAttr(
  link: HTMLLinkElement,
  name: string,
  value: string | null,
): void {
  if (value) {
    link.setAttribute(name, value);
  } else {
    link.removeAttribute(name);
  }
}

function applyDatapawFavicon(): void {
  const link = ensureFaviconLink();
  managedLink = link;
  captureOriginalFavicon(link);
  link.rel = "icon";
  link.type = "image/x-icon";
  link.href =
    (
      window as {
        QwenPaw?: { host?: { getApiUrl?: (path: string) => string } };
      }
    ).QwenPaw?.host?.getApiUrl?.(DATAPAW_FAVICON_PATH) ??
    `/api${DATAPAW_FAVICON_PATH}`;
}

function restoreOriginalFavicon(): void {
  const link = managedLink ?? findFaviconLink();
  if (!link) return;

  const original = originalFavicon ?? {
    href: DEFAULT_FAVICON_HREF,
    rel: "icon",
    type: "image/svg+xml",
    sizes: null,
  };

  link.rel = original.rel;
  link.href = original.href;
  setOptionalAttr(link, "type", original.type);
  setOptionalAttr(link, "sizes", original.sizes);
}

function syncFavicon(): void {
  const isDatapaw = getSelectedAgentId() === DATAPAW_AGENT_ID;
  if (lastIsDatapaw === isDatapaw) return;

  lastIsDatapaw = isDatapaw;
  if (isDatapaw) {
    applyDatapawFavicon();
  } else {
    restoreOriginalFavicon();
  }
}

export function installDatapawFaviconPatch(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;

  syncFavicon();
  timer = window.setInterval(syncFavicon, SYNC_INTERVAL_MS);
  window.addEventListener("storage", syncFavicon);
  window.addEventListener("pageshow", syncFavicon);
  document.addEventListener("visibilitychange", syncFavicon);
}
