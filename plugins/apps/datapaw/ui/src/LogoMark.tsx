import { useState } from "react";

export const DATAPAW_LOGO_URL =
  "/api/frontend_plugin/datapaw/files/ui/dist/app/logo-mark-v4.png";

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
