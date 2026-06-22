import type { FileItem } from './types';

export type DrawerFileItem = FileItem & { _nodeName?: string };

export type ArtifactPreviewKind =
  | 'image'
  | 'html'
  | 'markdown'
  | 'csv'
  | 'json'
  | 'python'
  | 'text';

const PYTHON_MIME_TYPES = new Set([
  'text/x-python',
  'text/x-script.python',
  'application/x-python',
  'application/x-python-code',
  'application/x-python-script',
]);

const IMAGE_EXTENSIONS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'ico',
  'svg',
]);

const TEXT_EXTENSIONS = new Set([
  'txt',
  'log',
  'yaml',
  'yml',
  'xml',
  'sql',
  'js',
  'ts',
  'jsx',
  'tsx',
  'css',
  'less',
  'scss',
  'sh',
  'bash',
  'zsh',
  'toml',
  'ini',
  'cfg',
  'conf',
  'env',
  'tsv',
  'ndjson',
]);

const EXTENSION_MIME: Record<string, string> = {
  py: 'text/x-python',
  md: 'text/markdown',
  markdown: 'text/markdown',
  csv: 'text/csv',
  tsv: 'text/tab-separated-values',
  json: 'application/json',
  jsonl: 'application/x-ndjson',
  ndjson: 'application/x-ndjson',
  html: 'text/html',
  htm: 'text/html',
  txt: 'text/plain',
  log: 'text/plain',
  yaml: 'text/yaml',
  yml: 'text/yaml',
  xml: 'text/xml',
  sql: 'application/sql',
  js: 'text/javascript',
  ts: 'text/typescript',
  jsx: 'text/javascript',
  tsx: 'text/typescript',
  css: 'text/css',
  less: 'text/plain',
  scss: 'text/plain',
  sh: 'text/x-shellscript',
  bash: 'text/x-shellscript',
  zsh: 'text/x-shellscript',
  toml: 'text/plain',
  ini: 'text/plain',
  cfg: 'text/plain',
  conf: 'text/plain',
  env: 'text/plain',
  svg: 'image/svg+xml',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  bmp: 'image/bmp',
  ico: 'image/x-icon',
};

function shouldInferMime(mimeType: string): boolean {
  const mime = (mimeType || '').trim().toLowerCase();
  return !mime || mime === 'application/octet-stream';
}

export function getArtifactFileExtension(file: {
  name?: string;
  path?: string;
}): string {
  const name = (file.name || file.path || '').trim();
  const base = name.split('/').pop() || name;
  const dot = base.lastIndexOf('.');
  if (dot <= 0) return '';
  return base.slice(dot + 1).toLowerCase();
}

/** Infer MIME from filename when API returns empty or generic octet-stream. */
export function inferArtifactMimeType(name: string, mimeType = ''): string {
  const mime = (mimeType || '').trim();
  if (!shouldInferMime(mime)) return mime;
  const ext = getArtifactFileExtension({ name });
  return EXTENSION_MIME[ext] || mime;
}

/** Whether an artifact should be previewed as Python source. */
export function isPythonArtifactFile(file: {
  name?: string;
  mime_type?: string;
  path?: string;
}): boolean {
  const ext = getArtifactFileExtension(file);
  if (ext === 'py') return true;
  const mime = inferArtifactMimeType(
    file.name || file.path || '',
    file.mime_type || '',
  ).toLowerCase();
  return PYTHON_MIME_TYPES.has(mime) || mime.includes('python');
}

export function isJsonArtifactFile(file: {
  name?: string;
  mime_type?: string;
  path?: string;
}): boolean {
  const ext = getArtifactFileExtension(file);
  if (ext === 'json' || ext === 'jsonl' || ext === 'ndjson') return true;
  const mime = inferArtifactMimeType(
    file.name || file.path || '',
    file.mime_type || '',
  ).toLowerCase();
  return mime === 'application/json' || mime.includes('json');
}

export function resolveArtifactPreviewKind(file: {
  name?: string;
  mime_type?: string;
  path?: string;
}): ArtifactPreviewKind {
  const name = file.name || file.path || '';
  const mime = inferArtifactMimeType(name, file.mime_type || '').toLowerCase();
  const ext = getArtifactFileExtension(file);

  if (mime.startsWith('image/') || IMAGE_EXTENSIONS.has(ext)) return 'image';
  if (mime === 'text/html' || ext === 'html' || ext === 'htm') return 'html';
  if (mime === 'text/markdown' || ext === 'md' || ext === 'markdown') {
    return 'markdown';
  }
  if (mime === 'text/csv' || ext === 'csv') return 'csv';
  if (isJsonArtifactFile(file)) return 'json';
  if (isPythonArtifactFile(file)) return 'python';
  if (
    mime.startsWith('text/') ||
    mime === 'application/sql' ||
    mime === 'application/xml' ||
    mime === 'application/x-ndjson' ||
    TEXT_EXTENSIONS.has(ext)
  ) {
    return 'text';
  }
  if (ext) return 'text';
  return 'text';
}

export function normalizeArtifactFile<
  T extends { name?: string; path?: string; mime_type?: string },
>(file: T): T {
  const name = file.name || file.path?.split('/').pop() || '';
  const mime_type = inferArtifactMimeType(name, file.mime_type || '');
  if (mime_type === file.mime_type) return file;
  return { ...file, mime_type };
}

const FILE_FIELDS = [
  'name',
  'path',
  'mime_type',
  'size_bytes',
  'preview_url',
  'download_url',
  'graph_id',
  'node_id',
] as const;

/** Normalize API / plan file entries to plain serializable objects for rendering. */
export function normalizeDrawerFile(file: unknown, nodeName?: string): DrawerFileItem | null {
  if (!file || typeof file !== 'object') return null;
  const src = file as Record<string, unknown>;
  const path = typeof src.path === 'string' ? src.path : '';
  const name = typeof src.name === 'string' ? src.name : path.split('/').pop() || 'file';
  if (!path && !name) return null;

  const out: DrawerFileItem = { name, path, mime_type: '', size_bytes: 0 };
  for (const key of FILE_FIELDS) {
    const value = src[key];
    if (value === undefined || value === null) continue;
    if (key === 'size_bytes' && typeof value === 'number') {
      out.size_bytes = value;
    } else if (typeof value === 'string') {
      (out as Record<string, unknown>)[key] = value;
    }
  }
  out.mime_type = inferArtifactMimeType(name, out.mime_type);
  if (nodeName) out._nodeName = nodeName;
  else if (typeof src._nodeName === 'string') out._nodeName = src._nodeName;
  return out;
}

export function collectDrawerFiles(
  nodeFiles: unknown,
  allFiles: unknown,
  nodeName?: string,
): DrawerFileItem[] {
  const preferAll = Array.isArray(allFiles) && allFiles.length > 0;
  const raw: unknown[] = preferAll
    ? [...allFiles]
    : Array.isArray(nodeFiles)
      ? [...nodeFiles]
      : [];

  const seen = new Set<string>();
  const result: DrawerFileItem[] = [];
  for (const item of raw) {
    const normalized = normalizeDrawerFile(item, preferAll ? undefined : nodeName);
    if (!normalized) continue;
    const key = normalized.path || normalized.name;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(normalized);
  }
  return result;
}

export function safeFormatJson(text: string, maxLen = 512_000): string {
  const trimmed = text.length > maxLen ? text.slice(0, maxLen) : text;
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    const lines = trimmed.split('\n').filter((line) => line.trim());
    if (lines.length > 1) {
      try {
        return lines
          .map((line) => JSON.stringify(JSON.parse(line), null, 2))
          .join('\n\n');
      } catch {
        /* fall through */
      }
    }
    return trimmed;
  }
}
