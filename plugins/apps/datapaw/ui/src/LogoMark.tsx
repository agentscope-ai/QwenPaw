import { useState } from "react";

export const DATAPAW_LOGO_URL =
  "/api/frontend_plugin/datapaw/files/ui/dist/app/logo-mark-v4.png";

/** Full wordmark shipped with the vendored Context console build. */
export const DATAPAW_WORDMARK_URL =
  "/api/frontend_plugin/datapaw/files/ui/dist/context-console/qwenpaw-data-wordmark.png";

export function LogoMark() {
  const [failed, setFailed] = useState(false);

  return failed ? (
    <span className="datapaw-logo-fallback" aria-hidden="true">
      DP
    </span>
  ) : (
    <img src={DATAPAW_LOGO_URL} alt="" onError={() => setFailed(true)} />
  );
}

export function WordmarkLogo() {
  const [failed, setFailed] = useState(false);

  return failed ? (
    <b className="datapaw-topbar__fallback">QwenPaw-Data</b>
  ) : (
    <img
      src={DATAPAW_WORDMARK_URL}
      alt="QwenPaw-Data"
      onError={() => setFailed(true)}
    />
  );
}
