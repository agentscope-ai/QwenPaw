import { useState } from "react";

export const QWENPAW_DATA_LOGO_URL =
  "/api/frontend_plugin/qwenpaw-data/files/ui/dist/app/logo-mark-v4.png";

/** Full wordmark shipped with the vendored Context console build. */
export const QWENPAW_DATA_WORDMARK_URL =
  "/api/frontend_plugin/qwenpaw-data/files/ui/dist/context-console/qwenpaw-data-wordmark.png";

export function LogoMark() {
  const [failed, setFailed] = useState(false);

  return failed ? (
    <span className="qwenpaw-data-logo-fallback" aria-hidden="true">
      DP
    </span>
  ) : (
    <img src={QWENPAW_DATA_LOGO_URL} alt="" onError={() => setFailed(true)} />
  );
}

export function WordmarkLogo() {
  const [failed, setFailed] = useState(false);

  return failed ? (
    <b className="qwenpaw-data-topbar__fallback">QwenPaw-Data</b>
  ) : (
    <img
      src={QWENPAW_DATA_WORDMARK_URL}
      alt="QwenPaw-Data"
      onError={() => setFailed(true)}
    />
  );
}
