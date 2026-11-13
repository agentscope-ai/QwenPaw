import { useLayoutEffect } from "react";
import logo from "../../public/online.svg?raw";

const faviconLogo = logo
  .replace(/width="[^"]*"/, 'width="24"')
  .replace(/height="[^"]*"/, 'height="32"');

export function useSessionFavicon(running: boolean, unread: boolean) {
  useLayoutEffect(() => {
    if (!running && !unread) return;

    const existing =
      document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    const icon = existing ?? document.createElement("link");
    const originalHref = icon.getAttribute("href");
    const originalType = icon.getAttribute("type");
    const color = running ? "#00a5fb" : "#52c41a";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${faviconLogo}<circle cx="26" cy="6" r="5" fill="${color}" stroke="white" stroke-width="1.5"/></svg>`;
    icon.rel = "icon";
    icon.type = "image/svg+xml";
    icon.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
    if (!existing) document.head.appendChild(icon);

    return () => {
      if (!existing) {
        icon.remove();
        return;
      }
      if (originalHref === null) icon.removeAttribute("href");
      else icon.setAttribute("href", originalHref);
      if (originalType === null) icon.removeAttribute("type");
      else icon.setAttribute("type", originalType);
    };
  }, [running, unread]);
}
