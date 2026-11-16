/**
 * Volume-root detection for project directories.
 *
 * A sandbox ACE is inheritable and is written on the workspace, on every
 * mount and on every deny path. A volume root has no parent, so such a
 * write re-propagates across the whole volume and can leave the drive
 * inaccessible. The backend refuses to sandbox such a path (see #7943);
 * the console uses this to warn before the user picks one.
 *
 * Mirrors `is_volume_root` in `src/qwenpaw/sandbox/config.py`.
 */
export function isVolumeRoot(path: string): boolean {
  const raw = (path ?? "").trim();
  if (!raw) {
    return false;
  }

  // Normalise separators, then drop trailing ones ("C:\\" -> "C:").
  let normalised = raw.replace(/\\/g, "/");
  while (normalised.length > 1 && normalised.endsWith("/")) {
    normalised = normalised.slice(0, -1);
  }

  // POSIX root: "/"
  if (normalised === "/") {
    return true;
  }
  // Windows drive root: "C:" / "C:/"
  if (/^[a-zA-Z]:$/.test(normalised)) {
    return true;
  }
  // UNC share root: "//server/share" (also has no parent)
  if (/^\/\/[^/]+\/[^/]+$/.test(normalised)) {
    return true;
  }
  return false;
}
