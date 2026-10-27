/*
 * 聊天媒体「保存到相册 / 系统分享」—— 对齐 PR #7378 features/chat/mediaActions.ts。
 *
 * 取址与命名同 7378：URL 走 mediaUrl（本工程在 ChatDetailPage 内，http/https/data 原样、相对路径拼
 * {base}/api/files/preview）；文件名取 part.name 或 URL 末段，非法字符替换、截断 100。
 * 落盘：下载到应用缓存目录（filesDir/cache）后再消费。
 *
 * 权限口径：本工程只声明 ohos.permission.INTERNET，故「保存到相册」不用 MediaLibrary 权限申请，
 * 而走官方安全控件 SaveButton ——「点击即临时获得存储权限（1 分钟内单次访问媒体库特权接口）」，
 * 与 7378 的 requestPermissionsAsync 路线等价但无需声明权限。
 * 分享走 ShareKit 分享面板（系统分享，无需权限）。
 */

import { common, Want, wantConstant } from '@kit.AbilityKit';
import { fileIo, picker } from '@kit.CoreFileKit';
import { filePreview } from '@kit.PreviewKit';
import { fileUri } from '@kit.CoreFileKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { systemShare } from '@kit.ShareKit';
import { uniformTypeDescriptor as utd } from '@kit.ArkData';
import { http } from '@kit.NetworkKit';
import { atlsRequest } from './AtlsTransport';
import { QpConnection, loadConnection } from './ConnectionStore';

// 与 7378 defaultName 同口径
export function defaultNameOf(type: string): string {
  if (type === 'image') {
    return 'qwenpaw-image.png';
  }
  if (type === 'video') {
    return 'qwenpaw-video.mp4';
  }
  if (type === 'audio') {
    return 'qwenpaw-audio.m4a';
  }
  return 'qwenpaw-file';
}

// 与 7378 safeName 同口径：仅保留字母数字/下划线/点/中横/汉字，取末 100 字符
export function safeNameOf(value: string, type: string): string {
  const cleaned: string = value.replace(/[^\w.\-一-鿿]/g, '-').slice(-100);
  return cleaned.length > 0 ? cleaned : defaultNameOf(type);
}

function cacheDirOf(ctx: common.Context): string {
  return `${ctx.cacheDir}/${Date.now()}-`;
}

// 取媒体接口所需的鉴权头：相对路径的媒体走本机 QwenPaw 的 /api/files/preview，与其他请求同源，
// 必须带同一套 Bearer/X-Agent-Id（否则 401，保存与分享静默失败）；绝对 URL（第三方/内联 data）
// 一律不带凭据，避免把令牌发给外部主机。
async function authHeadersOf(ctx: common.Context, url: string): Promise<Record<string, Object>> {
  const header: Record<string, Object> = {};
  const conn: QpConnection | null = await loadConnection(ctx);
  if (conn !== null && url.startsWith(conn.baseUrl)) {
    if (conn.token.length > 0) {
      header['Authorization'] = `Bearer ${conn.token}`;
    }
    if (conn.agentId.length > 0) {
      header['X-Agent-Id'] = conn.agentId;
    }
  }
  return header;
}

/** 下载媒体到应用缓存目录，返回文件路径；失败抛错（调用方给 toast）。 */
export async function downloadToCache(ctx: common.Context, url: string, type: string, name: string): Promise<string> {
  const resp: http.HttpResponse = await atlsRequest({
    url: url,
    method: http.RequestMethod.GET,
    header: await authHeadersOf(ctx, url),
    connectMs: 15000,
    readMs: 60000,
    binary: true
  });
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new Error(`HTTP ${resp.responseCode}`);
  }
  const buf: ArrayBuffer = resp.result as ArrayBuffer;
  const path: string = cacheDirOf(ctx) + safeNameOf(name, type);
  const f = fileIo.openSync(path, fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE);
  fileIo.writeSync(f.fd, buf);
  fileIo.closeSync(f);
  return path;
}

/**
 * 把内存里的字节落到缓存目录（内联 base64 媒体要交给系统预览/分享时必须先有文件）：
 * 命名规则与 downloadToCache 一致，返回缓存路径；写失败抛错。
 */
export function saveBytesToCache(ctx: common.Context, bytes: Uint8Array, name: string): string {
  const buf: ArrayBuffer =
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  const path: string = cacheDirOf(ctx) + safeNameOf(name, 'file');
  const f = fileIo.openSync(path, fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE);
  fileIo.writeSync(f.fd, buf);
  fileIo.closeSync(f);
  return path;
}

/** 安全控件 SaveButton 回调内调用：已拿到临时授权，创建媒体库资源并写入文件内容。 */
export async function saveToGallery(ctx: common.Context, type: string, path: string): Promise<void> {
  const helper: photoAccessHelper.PhotoAccessHelper = photoAccessHelper.getPhotoAccessHelper(ctx);
  let photoType: photoAccessHelper.PhotoType = photoAccessHelper.PhotoType.IMAGE;
  let ext: string = 'png';
  if (type === 'video') {
    photoType = photoAccessHelper.PhotoType.VIDEO;
    ext = 'mp4';
  } else if (type !== 'image') {
    photoType = photoAccessHelper.PhotoType.IMAGE;
    ext = 'bin';
  }
  const uri: string = await helper.createAsset(photoType, ext);
  const src = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
  const dst = fileIo.openSync(uri, fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE);
  try {
    const stat = fileIo.statSync(src.fd);
    const buf = new ArrayBuffer(stat.size);
    fileIo.readSync(src.fd, buf);
    fileIo.writeSync(dst.fd, buf);
  } finally {
    fileIo.closeSync(src);
    fileIo.closeSync(dst);
  }
}

// 扩展名 → mimeType（对齐 Preview Kit《filePreview（文件预览）》支持类型表：
// 文本/代码、图片、音视频、Office、pdf 等；未列出的后缀传空串，系统按 uri 后缀自行判断格式）
const PREVIEW_MIME: Record<string, string> = {
  // 文本 / 代码 / 网页：官方支持表里逐项补齐（缺一项该后缀就走不了系统预览）
  'txt': 'text/plain',
  'cpp': 'text/x-c++src',
  'c': 'text/x-csrc',
  'h': 'text/x-chdr',
  'java': 'text/x-java',
  'xhtml': 'application/xhtml+xml',
  'xml': 'text/xml',
  'html': 'text/html',
  'htm': 'text/html',
  'pdf': 'application/pdf',
  'doc': 'application/msword',
  'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'xls': 'application/vnd.ms-excel',
  'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'ppt': 'application/vnd.ms-powerpoint',
  'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'csv': 'text/csv',
  'ofd': 'general.ofd',
  'jpg': 'image/jpeg',
  'jpeg': 'image/jpeg',
  'png': 'image/png',
  'gif': 'image/gif',
  'webp': 'image/webp',
  'bmp': 'image/bmp',
  'svg': 'image/svg+xml',
  'mp4': 'video/mp4',
  'mkv': 'video/x-matroska',
  'ts': 'video/mp2ts',
  'm4a': 'audio/mp4a-latm',
  'aac': 'audio/aac',
  'mp3': 'audio/mpeg',
  'ogg': 'audio/ogg',
  'wav': 'audio/x-wav'
};

/** 文件名 → 预览用 mimeType（未命中返回空串，交由系统按后缀判断）。 */
export function previewMimeOf(name: string): string {
  const dot: number = name.lastIndexOf('.');
  if (dot < 0) {
    return '';
  }
  const mime: string = PREVIEW_MIME[name.slice(dot + 1).toLowerCase()];
  return typeof mime === 'string' ? mime : '';
}

/** 该文件是否落在 Preview Kit 的支持面内（命中才走系统预览；未命中的文本类由调用方给页内预览）。 */
export function canSystemPreview(name: string): boolean {
  return previewMimeOf(name).length > 0;
}

/** markdown 判据：页内预览走 vendor/markdown 渲染（与文件页同一口径）。 */
export function isMarkdownName(name: string): boolean {
  const lower: string = name.toLowerCase();
  return lower.endsWith('.md') || lower.endsWith('.markdown');
}

// 扩展名 → 是否按纯文本读（Preview Kit 不支持、但内容可读的文件走页内只读预览）
const TEXTUAL_EXT: string[] = [
  'txt', 'md', 'markdown', 'json', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env',
  'log', 'csv', 'tsv', 'sh', 'bash', 'zsh', 'py', 'rb', 'go', 'rs', 'kt', 'cs', 'js', 'jsx',
  'ts', 'tsx', 'sql', 'css', 'scss', 'gradle', 'properties', 'pl', 'lua', 'php', 'swift', 'vue'
];

/** 纯文本判据（按扩展名）。 */
export function isTextualName(name: string): boolean {
  const dot: number = name.lastIndexOf('.');
  if (dot < 0) {
    return false;
  }
  return TEXTUAL_EXT.indexOf(name.slice(dot + 1).toLowerCase()) >= 0;
}

/**
 * 隐式 Want / 系统预览用的 mimeType：先查 Preview Kit 支持表，文本类兜底 text/plain，
 * 其余给 application/octet-stream。
 * 为什么不能留空：官方《拉起文件处理类应用（startAbility）》表 1 明确 —— 传 type 时必须与 uri 的
 * 文件类型一致，否则匹配不到合适应用（FAQ《拉起第三方应用打开文件失败》同口径）；
 * 而 Preview Kit 的 mimeType 留空是"按 uri 后缀自行判断"，两处语义不同，故分开两个出口。
 */
export function mimeOf(name: string): string {
  const known: string = previewMimeOf(name);
  if (known.length > 0) {
    return known;
  }
  return isTextualName(name) ? 'text/plain' : 'application/octet-stream';
}

/** 页内只读预览的读取结果：内容可能被截断（大文件只读前 cap 字节）。 */
export interface TextRead {
  text: string;
  truncated: boolean;
}

/** 读缓存里的文本文件（页内预览用）：读失败返回空内容，超大文件按 cap 截断。 */
export function readTextFile(path: string, cap: number): TextRead {
  try {
    const size: number = fileIo.statSync(path).size;
    const length: number = size > cap ? cap : size;
    const text: string = fileIo.readTextSync(path, { offset: 0, length: length, encoding: 'utf-8' });
    return { text: text, truncated: size > cap };
  } catch (e) {
    return { text: '', truncated: false };
  }
}

/**
 * 「保存到…」：系统保存对话框选位置后按字节复制缓存文件（官方 picker 免权限声明）。
 * 入参是缓存路径 —— 预览/分享/保存共用同一次下载，调用方自己决定下载时机。
 * 返回 false = 用户取消。
 */
export async function saveCachedFileWithPicker(ctx: common.UIAbilityContext, path: string,
  name: string): Promise<boolean> {
  const saveOptions: picker.DocumentSaveOptions = new picker.DocumentSaveOptions();
  saveOptions.newFileNames = [name.length > 0 ? name : 'qwenpaw-file'];
  const view: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
  const uris: string[] = await view.save(saveOptions);
  if (uris.length === 0) {
    return false;
  }
  // 目标是 picker 授权的 file:// 文档 URI：copyFileSync 的 dest「路径」形参按沙箱路径解析，
  // 直接传 URI 会建出 0 字节文件（不抛错）。须两端 openSync 取 fd 再拷贝——dest 经 openSync(uri)
  // 拿到授权可写句柄，TRUNC 覆盖 picker 预建的空文件。
  const src: fileIo.File = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
  const dest: fileIo.File = fileIo.openSync(uris[0],
    fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
  try {
    fileIo.copyFileSync(src.fd, dest.fd);
  } finally {
    fileIo.closeSync(src);
    fileIo.closeSync(dest);
  }
  return true;
}

/**
 * 「其他应用打开」：官方《拉起文件处理类应用（startAbility）》口径 —— action 固定
 * ohos.want.action.viewData + uri + **非空** type（mimeOf，须与 uri 的文件类型一致，否则匹配不到
 * 应用）+ 读写双授权 flags；沙箱文件经 fileUri 转授权。
 */
export async function openCachedFileWithOtherApp(ctx: common.UIAbilityContext, path: string,
  name: string): Promise<void> {
  const want: Want = {
    action: 'ohos.want.action.viewData',
    uri: fileUri.getUriFromPath(path),
    type: mimeOf(name),
    flags: wantConstant.Flags.FLAG_AUTH_WRITE_URI_PERMISSION
      | wantConstant.Flags.FLAG_AUTH_READ_URI_PERMISSION
  };
  await ctx.startAbility(want);
}

/**
 * 用系统预览服务（Preview Kit）打开已落到缓存的文件：不预览自建渲染器，Office 由 WPS 提供能力，
 * 文本/图片/音视频都由系统预览界面渲染；失败时抛错，由调用方决定退路（另存 / 分享）。
 */
export async function openCachedFilePreview(ctx: common.UIAbilityContext, path: string, name: string): Promise<void> {
  await filePreview.openPreview(ctx, {
    title: name,
    uri: fileUri.getUriFromPath(path),
    mimeType: previewMimeOf(name)
  });
}

/** 系统分享面板（ShareKit）；anchorId 为分享面板贴靠的控件 id。 */
export function shareFile(ctx: common.UIAbilityContext, path: string, type: string, anchorId: string): void {
  let dataType: string = utd.UniformDataType.FILE;
  if (type === 'image') {
    dataType = utd.UniformDataType.IMAGE;
  } else if (type === 'video') {
    dataType = utd.UniformDataType.VIDEO;
  } else if (type === 'audio') {
    dataType = utd.UniformDataType.AUDIO;
  }
  const data: systemShare.SharedData = new systemShare.SharedData({
    utd: dataType,
    uri: `file://${path}`
  });
  const controller: systemShare.ShareController = new systemShare.ShareController(data);
  controller.show(ctx, { anchor: anchorId });
}
