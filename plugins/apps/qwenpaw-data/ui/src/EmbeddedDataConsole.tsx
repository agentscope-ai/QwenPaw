import { useEffect, useRef, useState } from "react";

/**
 * Same-origin static build of the engine console (the Data-Cloud host-core
 * console frontend), refreshed by scripts/update-data-console.sh. The build uses
 * hash routing, so tab switches navigate the live iframe without reloading
 * it — chat runs keep streaming while other pages are visible.
 */
const CONSOLE_INDEX =
  "/frontend_plugin/qwenpaw-data/files/ui/dist/data-console/index.html";

type Availability = "checking" | "ready" | "missing";

export function EmbeddedDataConsole({
  route,
  active,
}: {
  route: string;
  active: boolean;
}) {
  const indexUrl =
    window.QwenPaw?.host?.getApiUrl(CONSOLE_INDEX) ?? `/api${CONSOLE_INDEX}`;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const initialRouteRef = useRef(route);
  const [availability, setAvailability] = useState<Availability>("checking");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(indexUrl, { method: "GET", cache: "no-cache" })
      .then((response) => {
        if (!cancelled) setAvailability(response.ok ? "ready" : "missing");
      })
      .catch(() => {
        if (!cancelled) setAvailability("missing");
      });
    return () => {
      cancelled = true;
    };
  }, [indexUrl]);

  useEffect(() => {
    if (!loaded) return;
    const frameWindow = iframeRef.current?.contentWindow;
    if (!frameWindow) return;
    try {
      const target = `#${route}`;
      if (frameWindow.location.hash !== target) {
        frameWindow.location.hash = target;
      }
    } catch {
      // A cross-origin frame cannot be navigated; leave it untouched.
    }
  }, [route, loaded]);

  if (availability === "missing") {
    return (
      <div className="qwenpaw-data-embedded-console__empty">
        <b>Analysis console installation is incomplete</b>
        <p>
          The embedded Data console is missing from this app package. Reinstall
          QwenPaw-Data or ask the package maintainer for a complete build.
        </p>
      </div>
    );
  }

  return (
    <div className="qwenpaw-data-embedded-console">
      {availability === "checking" || !loaded ? (
        <div
          className="qwenpaw-data-embedded-console__loading"
          aria-hidden={active ? undefined : true}
        >
          Loading console…
        </div>
      ) : null}
      {availability === "ready" ? (
        <iframe
          ref={iframeRef}
          src={`${indexUrl}#${initialRouteRef.current}`}
          title="QwenPaw-Data analysis console"
          onLoad={() => setLoaded(true)}
        />
      ) : null}
    </div>
  );
}
