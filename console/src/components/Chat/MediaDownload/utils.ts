function decodeFilename(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function mediaFilenameFromUrl(
  url: string,
  fallbackFilename: string,
): string {
  if (url.startsWith("data:") || url.startsWith("blob:")) {
    return fallbackFilename;
  }
  const path = url.split(/[?#]/, 1)[0].replace(/\\/g, "/");
  const filename = path.split("/").pop();
  return filename ? decodeFilename(filename) : fallbackFilename;
}
