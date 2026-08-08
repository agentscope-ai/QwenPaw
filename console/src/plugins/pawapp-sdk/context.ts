let activePawAppId = "";

export function getPawAppIdFromPath(pathname: string): string {
  const match = pathname.match(/\/apps\/([^/?#]+)/);
  return match?.[1] ?? "";
}

export function setActivePawAppId(appId: string | null): void {
  activePawAppId = appId ?? "";
}

export function getActivePawAppId(): string {
  if (activePawAppId) return activePawAppId;
  return getPawAppIdFromPath(window.location.pathname);
}
