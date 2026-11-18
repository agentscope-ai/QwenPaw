/**
 * 上传文件像不像剧本：只用来决定要不要多问一句「登记为剧本」。
 *
 * 判定刻意保守——问错一次的代价是打断用户，漏问一次的代价只是回到原来的
 * 素材理解流程（行为与今天完全一致）。所以文本文件要「文件名像剧本」或
 * 「首屏有剧本特征」才问；Word/PDF 读不到正文，只有文件名像剧本时才问。
 *
 * 后缀集合与服务端 `api/file_script_routes.py`、
 * `services/project_files/script_document_text.py` 保持一致。
 */

export type ScriptUploadKind = "text" | "document" | "none";

const SCRIPT_TEXT_SUFFIXES = [
  ".md",
  ".markdown",
  ".txt",
  ".text",
  ".rst",
  ".srt",
  ".vtt",
];

const SCRIPT_DOCUMENT_SUFFIXES = [".pdf", ".doc", ".docx"];

// 只读首屏：够判断结构即可，不把整份文件读进内存。
const SNIFF_BYTES = 64 * 1024;

const SCRIPT_NAME_PATTERN =
  /(剧本|脚本|分集|第\s*[0-9一二三四五六七八九十百]+\s*[集话話场幕]|script|screenplay|ep\s*\d+)/i;

// 剧本正文的结构特征：命中两条以上才认为「像剧本」。
const SCRIPT_CONTENT_PATTERNS: RegExp[] = [
  /^\s{0,3}#{1,4}\s*\S/m,
  /^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[场幕集话]|场\s*\d+|SCENE\b|INT\.|EXT\.)/im,
  /\*\*[^*\n]{1,24}\*\*\s*[:：]/,
  /^\s*[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{0,11}\s*[:：]\s*\S/m,
  /^\s*>\s*\S/m,
];

/** 按后缀把文件分成「可直登文本 / 可抽正文文档 / 其它」。 */
export function scriptSuffixKind(name: string): ScriptUploadKind {
  const lower = (name || "").toLowerCase();
  if (SCRIPT_TEXT_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    return "text";
  }
  if (SCRIPT_DOCUMENT_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    return "document";
  }
  return "none";
}

export function looksLikeScriptName(name: string): boolean {
  return SCRIPT_NAME_PATTERN.test(name || "");
}

export function countScriptContentMarkers(sample: string): number {
  return SCRIPT_CONTENT_PATTERNS.filter((pattern) => pattern.test(sample || ""))
    .length;
}

async function readSample(file: File): Promise<string> {
  const blob = file.slice(0, SNIFF_BYTES);
  if (typeof blob.text === "function") {
    try {
      return await blob.text();
    } catch {
      return "";
    }
  }
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => resolve("");
    reader.readAsText(blob);
  });
}

/**
 * 判断这次上传值不值得问一句「登记为剧本」。
 *
 * 返回 `"none"` 时调用方必须按原来的素材上传流程继续，不做任何额外打扰。
 */
export async function detectScriptUpload(
  file: File,
): Promise<ScriptUploadKind> {
  const kind = scriptSuffixKind(file.name);
  if (kind === "none") return "none";
  if (kind === "document") {
    // Word/PDF 的正文在客户端读不出来，只认文件名。
    return looksLikeScriptName(file.name) ? "document" : "none";
  }
  if (looksLikeScriptName(file.name)) return "text";
  const sample = await readSample(file);
  return countScriptContentMarkers(sample) >= 2 ? "text" : "none";
}
