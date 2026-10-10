/*
 * 附件选择与暂存 —— 对齐 PR #7378 chat/[id].tsx 的 DocumentPicker（任意类型、多选）。
 * 选择器返回的是文档 URI；而上传接口只接受应用沙箱路径，
 * 因此统一把选中文件拷进 cacheDir，上传完成后由调用方删除临时文件。
 */
import { picker } from '@kit.CoreFileKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';

// 选中并已落到沙箱的待上传文件
export interface PickedFile {
  path: string;    // 沙箱绝对路径（上传用）
  name: string;    // 文件名（含后缀）
  mime: string;    // 按后缀推断的 MIME
  kind: string;    // image / video / audio / file（对齐 RN 的 mimeType 前缀判定）
}

// 后缀 → MIME（选择器不返回 MIME，按后缀推断；未知回落 application/octet-stream）
function mimeOf(name: string): string {
  const dot: number = name.lastIndexOf('.');
  const ext: string = dot >= 0 ? name.substring(dot + 1).toLowerCase() : '';
  if (ext === 'png') {
    return 'image/png';
  }
  if (ext === 'jpg' || ext === 'jpeg') {
    return 'image/jpeg';
  }
  if (ext === 'gif') {
    return 'image/gif';
  }
  if (ext === 'webp') {
    return 'image/webp';
  }
  if (ext === 'bmp') {
    return 'image/bmp';
  }
  if (ext === 'mp4') {
    return 'video/mp4';
  }
  if (ext === 'mov') {
    return 'video/quicktime';
  }
  if (ext === 'mp3') {
    return 'audio/mpeg';
  }
  if (ext === 'wav') {
    return 'audio/wav';
  }
  if (ext === 'm4a') {
    return 'audio/mp4';
  }
  if (ext === 'pdf') {
    return 'application/pdf';
  }
  if (ext === 'txt' || ext === 'md') {
    return 'text/plain';
  }
  if (ext === 'json') {
    return 'application/json';
  }
  if (ext === 'zip') {
    return 'application/zip';
  }
  return 'application/octet-stream';
}

// MIME → 内容类型（对齐 RN：image/video/audio 前缀，其余按文件）
export function kindOf(mime: string): string {
  if (mime.startsWith('image/')) {
    return 'image';
  }
  if (mime.startsWith('video/')) {
    return 'video';
  }
  if (mime.startsWith('audio/')) {
    return 'audio';
  }
  return 'file';
}

function nameOfUri(uri: string): string {
  const slash: number = uri.lastIndexOf('/');
  const raw: string = slash >= 0 ? uri.substring(slash + 1) : uri;
  return raw.length > 0 ? raw : `file_${Date.now()}`;
}

// 选中并拷入 cacheDir 的公共实现：uri → 沙箱文件（stampNames = 是否加时间戳前缀）
function copyPicked(ctx: common.Context, uri: string, stampNames: boolean): PickedFile {
  const rawName: string = nameOfUri(decodeURIComponent(uri));
  const name: string = stampNames ? `${Date.now()}_${rawName}` : rawName;
  const dest: string = `${ctx.cacheDir}/${name}`;
  const src: fs.File = fs.openSync(uri, fs.OpenMode.READ_ONLY);
  try {
    fs.copyFileSync(src.fd, dest);
  } finally {
    fs.closeSync(src);
  }
  const mime: string = mimeOf(rawName);
  const item: PickedFile = { path: dest, name: name, mime: mime, kind: kindOf(mime) };
  return item;
}

// 打开系统文件选择器（多选），并把选中文件逐个拷入 cacheDir
// stampNames = true：给文件名加时间戳前缀（聊天附件场景，避免同名互相覆盖）；
// stampNames = false：保留原文件名（工作区文件上传场景，落盘名要与所选文件一致）。
export async function pickFiles(ctx: common.Context,
  stampNames: boolean = true): Promise<PickedFile[]> {
  const options: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
  options.maxSelectNumber = 5;
  const view: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
  const uris: string[] = await view.select(options);
  const out: PickedFile[] = [];
  for (const uri of uris) {
    out.push(copyPicked(ctx, uri, stampNames));
  }
  return out;
}

// 单选 + 后缀过滤（导入项目 ZIP 等场景）；用户取消返回 null
export async function pickSingleFile(ctx: common.Context,
  suffixes: string[]): Promise<PickedFile | null> {
  const options: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
  options.maxSelectNumber = 1;
  if (suffixes.length > 0) {
    options.fileSuffixFilters = suffixes;
  }
  const view: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
  const uris: string[] = await view.select(options);
  if (uris.length === 0) {
    return null;
  }
  return copyPicked(ctx, uris[0], false);
}

// 上传完成后清理沙箱临时文件（失败忽略：文件可能已被系统回收）
export function removeTemp(path: string): void {
  try {
    fs.unlinkSync(path);
  } catch (e) {
    // 忽略：临时文件不存在无需处理
  }
}
