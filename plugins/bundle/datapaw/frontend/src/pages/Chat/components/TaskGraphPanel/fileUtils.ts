import type { FileItem } from './types';

export type DrawerFileItem = FileItem & { _nodeName?: string };

const PYTHON_MIME_TYPES = new Set([
  'text/x-python',
  'text/x-script.python',
  'application/x-python',
  'application/x-python-code',
  'application/x-python-script',
]);

/** Whether an artifact should be previewed as Python source. */
export function isPythonArtifactFile(file: {
  name?: string;
  mime_type?: string;
  path?: string;
}): boolean {
  const name = (file.name || file.path || '').toLowerCase();
  if (name.endsWith('.py')) return true;
  const mime = (file.mime_type || '').toLowerCase();
  return PYTHON_MIME_TYPES.has(mime) || mime.includes('python');
}

function inferMimeType(name: string, mimeType: string): string {
  if (mimeType) return mimeType;
  const lower = name.toLowerCase();
  if (lower.endsWith('.py')) return 'text/x-python';
  if (lower.endsWith('.md')) return 'text/markdown';
  if (lower.endsWith('.csv')) return 'text/csv';
  if (lower.endsWith('.json')) return 'application/json';
  if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'text/html';
  if (lower.endsWith('.txt') || lower.endsWith('.log')) return 'text/plain';
  return mimeType;
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
  out.mime_type = inferMimeType(name, out.mime_type);
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
    return trimmed;
  }
}
