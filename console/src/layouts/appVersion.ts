import api from "../api";

let versionRequest: Promise<string> | null = null;

/** Share the version request across header/sidebar consumers and remounts. */
export function getAppVersion(): Promise<string> {
  if (!versionRequest) {
    versionRequest = api
      .getVersion()
      .then((response) => response?.version ?? "")
      .catch((error: unknown) => {
        versionRequest = null;
        throw error;
      });
  }
  return versionRequest;
}
