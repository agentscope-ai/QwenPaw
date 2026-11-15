/** Best-effort local redaction. Always show the result for user review. */
export function redactReportText(text: string): string {
  return text
    .replace(
      /-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)/g,
      "[REDACTED PRIVATE KEY]",
    )
    .replace(
      /(["']?authorization["']?\s*[:=]\s*)["']?(?:bearer|basic)\s+[^\s,;"']+["']?/gi,
      "$1[REDACTED]",
    )
    .replace(
      /(["']?(?:cookie|set-cookie)["']?\s*[:=]\s*)[^\r\n]+/gi,
      "$1[REDACTED]",
    )
    .replace(
      /(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|token|client[_-]?secret)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;&]+)/gi,
      "$1[REDACTED]",
    )
    .replace(/\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}/g, "[REDACTED]")
    .replace(
      /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "[REDACTED JWT]",
    )
    .replace(/\b(https?:\/\/)[^\s/@:]+:[^\s/@]+@/gi, "$1[REDACTED]@")
    .replace(/\/(?:Users|home)\/[^/\s]+/g, "/[HOME]")
    .replace(/[a-z]:\\Users\\[^\\\s]+/gi, "[HOME]")
    .replace(/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g, "[REDACTED EMAIL]");
}

export function validateReportLink(url: string, kind: string): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.origin === "https://platform.agentscope.io" &&
      parsed.pathname === "/community/ask" &&
      !parsed.username &&
      !parsed.password &&
      !!parsed.searchParams.get(
        kind === "skill" ? "relatedSkillId" : "relatedPluginId",
      )
    );
  } catch {
    return false;
  }
}

/** Re-encode selected images locally to strip file metadata before review. */
export async function readReportScreenshot(file: File): Promise<string> {
  if (
    !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
    file.size > 8 * 1024 * 1024
  ) {
    throw new Error("invalid_image");
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (
      !image.naturalWidth ||
      image.naturalWidth * image.naturalHeight > 16_000_000
    ) {
      throw new Error("invalid_image");
    }
    const scale = Math.min(
      1,
      1280 / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.naturalWidth * scale);
    canvas.height = Math.round(image.naturalHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("invalid_image");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    URL.revokeObjectURL(url);
  }
}
