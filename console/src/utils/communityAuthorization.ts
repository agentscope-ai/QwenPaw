import {
  isDesktopTauriRuntime,
  openExternalLinkChecked,
} from "./openExternalLink";
import { getPyWebViewApi } from "./pywebview";

export function validAuthorizationUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.origin === "https://platform.agentscope.io" &&
      url.pathname === "/cli/login" &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

/** Reserve a browser tab during the click; desktop shells use the OS browser. */
export function reserveAuthorizationWindow(waiting: string): Window | null {
  if (isDesktopTauriRuntime() || getPyWebViewApi()?.open_external_link)
    return null;
  const popup = window.open("about:blank", "_blank");
  if (!popup) throw new Error("popup_blocked");
  popup.opener = null;
  const meta = popup.document.createElement("meta");
  meta.name = "referrer";
  meta.content = "no-referrer";
  popup.document.head.append(meta);
  popup.document.body.textContent = waiting;
  return popup;
}

export async function openAuthorizationUrl(url: string, popup: Window | null) {
  if (!validAuthorizationUrl(url)) throw new Error("invalid_authorization_url");
  if (popup) {
    if (popup.closed) throw new Error("popup_blocked");
    popup.location.replace(url);
  } else await openExternalLinkChecked(url);
}
