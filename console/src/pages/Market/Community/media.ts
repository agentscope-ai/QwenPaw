export function mediaUrl(value?: string): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value, "https://platform.agentscope.io");
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
export function videoUrl(value?: string): string | undefined {
  const safe = mediaUrl(value);
  if (!safe) return undefined;
  const url = new URL(safe);
  if (!/\.(mp4|webm|ogg|ogv|mov|m4v)$/i.test(url.pathname)) return undefined;
  url.searchParams.delete("x-oss-process");
  return url.href;
}
