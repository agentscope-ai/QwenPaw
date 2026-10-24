/*
 * 工作台模块 · Files —— 对齐 PR #7378 features/workbench/FilesSettings.tsx。
 *   GET  /api/workspace/tree?path=&limit=200&root=workspace              目录分页
 *   GET  /api/workspace/file-content?path=&offset=0&limit=262144         文本分片（truncated = 超出单次上限）
 *   PUT  /api/workspace/file-content?path=&root=workspace                保存文本
 *   GET  /api/workspace/file-download?path=&root=workspace               二进制下载
 *   POST /api/workspace/file-upload?path=&root=workspace&conflict=rename 多文件上传
 * 与 7378 一致：text / csv 进预览或编辑（超限只读预览），其余类型（image / pdf / binary）走下载保存；
 * 上传返回同名冲突时由服务端按 conflict=rename 安全重命名。
 * 半模态沿用统一件（SheetGate + moduleSheetOptions），预览与编辑共用一张面板、按模式切换内容
 * （同一组件挂多个 bindSheet 只有最后一个生效）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { atlsRequest, buildMultipart, MultipartFilePart, MultipartBody } from '../services/AtlsTransport';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { openCachedFilePreview,
  saveCachedFileWithPicker, openCachedFileWithOtherApp } from '../services/MediaActions';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { PickedFile, pickFiles, removeTemp } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { FileTreeRow } from './FileTreeRow';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { contextMenuOptions } from '../theme/MenuMaterial';
import { Markdown } from '../vendor/markdown/Index';
import { uiMaterial } from '@kit.ArkUI';
import { UiTokens } from '../theme/UiTokens';
import { accentColor } from '../theme/Accent';
import { t, tf } from '../services/I18n';

const TREE_LIMIT: number = 200;
const CHUNK_LIMIT: number = 256 * 1024;

class FileEntry {
  name: string = '';
  path: string = '';
  kind: string = 'file';        // file | directory
  size: number = -1;            // -1 = 目录（接口返回 null）
  previewKind: string = '';     // text | csv | image | pdf | binary | directory
}

// 文件树的一行（宽屏横排专用）：条目 + 缩进层级 + 该目录是否已展开
interface TreeRow {
  entry: FileEntry;
  depth: number;
  expanded: boolean;
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

// markdown 判据：文件页对 .md 默认渲染预览（渲染库见 vendor/markdown，来源与许可见该目录）
function isMarkdown(name: string): boolean {
  const lower: string = name.toLowerCase();
  return lower.endsWith('.md') || lower.endsWith('.markdown');
}

// 文本可编辑判据（对齐 7378：preview_kind 为空或 text/csv 才读文本）
function isTextual(previewKind: string): boolean {
  return previewKind.length === 0 || previewKind === 'text' || previewKind === 'csv';
}

function sizeLabel(size: number): string {
  if (size < 0) {
    return '';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function authHeader(conn: QpConnection): Record<string, Object> {
  const header: Record<string, Object> = { 'Accept': 'application/json' };
  if (conn.token.length > 0) {
    header['Authorization'] = `Bearer ${conn.token}`;
  }
  if (conn.agentId.length > 0) {
    header['X-Agent-Id'] = conn.agentId;
  }
  return header;
}

// 多文件上传（multipart，字段名对齐服务端 files: list[UploadFile]）
async function uploadWorkspaceFiles(conn: QpConnection, dir: string,
  files: PickedFile[]): Promise<void> {
  const parts: MultipartFilePart[] = [];
  for (const f of files) {
    parts.push({
      name: 'files',
      filePath: f.path,
      fileName: f.name,
      contentType: f.mime
    });
  }
  const multipart: MultipartBody = buildMultipart(parts);
  const header: Record<string, Object> = authHeader(conn);
  header['Content-Type'] = multipart.contentType;
  const url: string = `${conn.baseUrl}/api/workspace/file-upload?path=`
    + `${encodeURIComponent(dir)}&root=workspace&conflict=rename`;
  const resp: http.HttpResponse = await atlsRequest({
    url: url,
    method: http.RequestMethod.POST,
    header: header,
    bodyBytes: multipart.body,
    connectMs: 15000,
    readMs: 120000
  });
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new Error(tf($r('app.string.module_files_upload_failed'), resp.responseCode));
  }
}

// 取二进制内容（预览与保存共用同一次下载）
async function fetchWorkspaceFile(conn: QpConnection, entry: FileEntry): Promise<ArrayBuffer> {
  const header: Record<string, Object> = authHeader(conn);
  const url: string = `${conn.baseUrl}/api/workspace/file-download?path=`
    + `${encodeURIComponent(entry.path)}&root=workspace`;
  const resp: http.HttpResponse = await atlsRequest({
    url: url,
    method: http.RequestMethod.GET,
    header: header,
    connectMs: 15000,
    readMs: 120000,
    binary: true
  });
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new Error(tf($r('app.string.module_files_download_failed'), resp.responseCode));
  }
  return resp.result as ArrayBuffer;
}

// 文本落缓存文件（供「其他应用打开」交给外部应用读取）
function writeCacheText(ctx: common.Context, name: string, text: string): string {
  const path: string = `${ctx.cacheDir}/${Date.now()}-${name.length > 0 ? name : 'qwenpaw-file.md'}`;
  const file: fs.File = fs.openSync(path,
    fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
  try {
    fs.writeSync(file.fd, text);
  } finally {
    fs.closeSync(file);
  }
  return path;
}

// 写入应用缓存目录并返回路径：系统预览服务按 uri 读取（沙箱文件经 fileUri 转授权）
function writeCacheFile(ctx: common.Context, name: string, buffer: ArrayBuffer): string {
  const path: string = `${ctx.cacheDir}/${Date.now()}-${name.length > 0 ? name : 'qwenpaw-file'}`;
  const file: fs.File = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE);
  try {
    fs.writeSync(file.fd, buffer);
  } finally {
    fs.closeSync(file);
  }
  return path;
}

@Component
export struct ModuleFiles {
  @State dirPath: string = '';
  @State entries: FileEntry[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State busyLabel: string = '';
  // 宽屏横排（平板/电脑横屏；由 ModulePage 按整页实测尺寸判定后传入）：
  // 这种形态下点文件夹 = 原地展开成文件树，而不是整页进到该目录里
  @Prop wide: boolean = false;
  // 文件树：已展开的目录（按路径）与展平后的行序列（见 buildTree）
  @State treeOpen: string[] = [];
  @State treeRows: TreeRow[] = [];
  // 已取过的子目录内容（展开过一次就不再请求；重新 load 时清空）
  private childCache: Map<string, FileEntry[]> = new Map<string, FileEntry[]>();
  @State sheetShown: boolean = false;
  @State sheetEdit: boolean = false;      // false = 只读预览，true = 可编辑
  @State draftPath: string = '';
  @State draftText: string = '';
  // 当前长按弹出菜单的文件路径（bindContextMenu(isShown) 的判据，收起时复位）
  @State menuPath: string = '';
  // markdown 渲染预览态（打开 .md 默认渲染，可切回纯文本编辑）
  @State mdRendered: boolean = false;
  // 面板操作键材质（THIN；interactive = 交互形变、lightEffect = 点光源，替代默认按压态）
  private sheetBtnMaterial: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.load();
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async context(): Promise<common.UIAbilityContext> {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  // 列一层目录（GET /api/workspace/tree，单层、分页上限 TREE_LIMIT）：
  // 进目录与「文件树展开子目录」共用同一份实现
  private async listDir(path: string): Promise<FileEntry[]> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error(t($r('app.string.module_not_connected')));
    }
    const url: string = `${c.baseUrl}/api/workspace/tree?path=${encodeURIComponent(path)}`
      + `&limit=${TREE_LIMIT}&root=workspace`;
    const resp: http.HttpResponse = await doRequest(url, http.RequestMethod.GET, null,
      c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    const data: Record<string, Object> = jsonOf(resp);
    const arr: Object = data['entries'];
    const out: FileEntry[] = [];
    if (Array.isArray(arr)) {
      for (const item of arr as Object[]) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const e: FileEntry = new FileEntry();
        e.name = strOf(r['name'], '');
        e.path = strOf(r['path'], '');
        e.kind = strOf(r['kind'], 'file');
        e.previewKind = strOf(r['preview_kind'], '');
        const size: Object = r['size'];
        e.size = typeof size === 'number' ? size as number : -1;
        out.push(e);
      }
    }
    return out;
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = await this.context();
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      this.entries = await this.listDir(this.dirPath);
      // 换了一层目录：展开态与子目录缓存都作废，按新的一层重建
      this.childCache.clear();
      this.treeOpen = [];
      this.buildTree();
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  // ============ 文件树（宽屏横排）============
  // 已展开目录按层级展平成一行一行的序列（展开态是树唯一的可变状态，行序列由它派生）
  private buildTree(): void {
    const rows: TreeRow[] = [];
    this.pushLevel(this.entries, 0, rows);
    this.treeRows = rows;
  }

  private pushLevel(list: FileEntry[], depth: number, rows: TreeRow[]): void {
    for (const e of list) {
      const dir: boolean = e.kind === 'directory';
      const open: boolean = dir && this.treeOpen.indexOf(e.path) >= 0;
      const r: TreeRow = { entry: e, depth: depth, expanded: open };
      rows.push(r);
      if (open) {
        const kids: FileEntry[] | undefined = this.childCache.get(e.path);
        if (kids !== undefined) {
          this.pushLevel(kids, depth + 1, rows);
        }
      }
    }
  }

  // 文件树里点文件夹：原地展开 / 收起（首次展开才去取子目录，之后走缓存）
  private async toggleFolder(e: FileEntry): Promise<void> {
    const next: string[] = this.treeOpen.slice();
    const at: number = next.indexOf(e.path);
    if (at >= 0) {
      next.splice(at, 1);
      this.treeOpen = next;
      this.buildTree();
      return;
    }
    if (this.childCache.get(e.path) === undefined) {
      this.busy = true;
      this.busyLabel = t($r('app.string.module_files_loading'));
      try {
        this.childCache.set(e.path, await this.listDir(e.path));
      } catch (err) {
        this.toast((err as Error).message);
        this.busy = false;
        this.busyLabel = '';
        return;
      }
      this.busy = false;
      this.busyLabel = '';
    }
    next.push(e.path);
    this.treeOpen = next;
    this.buildTree();
  }

  private openPreview(name: string, text: string): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetEdit = false;
    this.draftPath = '';
    this.draftText = text;
    this.sheetShown = true;
  }

  private openEditor(path: string, text: string): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetEdit = true;
    this.draftPath = path;
    this.draftText = text;
    this.sheetShown = true;
  }

  // 另存为：把当前文本（含未写回工作区的编辑内容）经系统 picker 存到用户选的目录
  // —— 与「保存」区分：保存 = 写回工作区原路径，另存为 = 导出到本地任意目录
  private async saveAsLocal(): Promise<void> {
    const ctx: common.UIAbilityContext = await this.context();
    const segs: string[] = this.draftPath.split('/');
    const name: string = segs.length > 0 ? segs[segs.length - 1] : 'qwenpaw-file.txt';
    try {
      // 与预览/分享共用同一套出口：先落缓存，再交给系统 picker 选目录
      const path: string = writeCacheText(ctx, name, this.draftText);
      const saved: boolean = await saveCachedFileWithPicker(ctx, path, name);
      if (saved) {
        this.toast(t($r('app.string.module_files_downloaded')));
      }
    } catch (err) {
      this.toast((err as Error).message);
    }
  }

  // 用其它应用打开当前文件（把编辑/预览中的文本落缓存再交给系统）
  private async openExternally(): Promise<void> {
    const ctx: common.UIAbilityContext = await this.context();
    const segs: string[] = this.draftPath.split('/');
    const name: string = segs.length > 0 ? segs[segs.length - 1] : 'qwenpaw-file.md';
    try {
      const path: string = writeCacheText(ctx, name, this.draftText);
      await openCachedFileWithOtherApp(ctx, path, name);
    } catch (err) {
      this.toast(t($r('app.string.module_files_open_external_failed')));
    }
  }

  // markdown 打开：默认渲染预览（只读），底部给「编辑」切到纯文本编辑
  private openMarkdown(path: string, text: string): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetEdit = false;
    this.mdRendered = true;
    this.draftPath = path;
    this.draftText = text;
    this.sheetShown = true;
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
    this.mdRendered = false;
  }

  private async openEntry(e: FileEntry): Promise<void> {
    if (e.kind === 'directory') {
      // 宽屏横排：文件夹原地展开成树（层级缩进可见），不再整页进到该目录里
      if (this.wide) {
        await this.toggleFolder(e);
        return;
      }
      this.dirPath = e.path;
      this.loaded = false;
      await this.load();
      return;
    }
    if (!isTextual(e.previewKind)) {
      await this.preview(e);
      return;
    }
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    this.busy = true;
    try {
      const url: string = `${c.baseUrl}/api/workspace/file-content?path=${encodeURIComponent(e.path)}`
        + `&offset=0&limit=${CHUNK_LIMIT}&root=workspace`;
      const resp: http.HttpResponse = await doRequest(url, http.RequestMethod.GET, null,
        c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const data: Record<string, Object> = jsonOf(resp);
      const content: string = strOf(data['content'], '');
      if (data['truncated'] === true) {
        this.openPreview(e.name, `${content}\n\n[${t($r('app.string.module_files_truncated'))}]`);
      } else if (isMarkdown(e.name)) {
        this.openMarkdown(e.path, content);
      } else {
        this.openEditor(e.path, content);
      }
    } catch (err) {
      this.toast((err as Error).message);
    } finally {
      this.busy = false;
    }
  }

  // 非文本文件：交给系统预览服务（Preview Kit）——Office 由 WPS 提供能力，预览界面自带
  // 「使用其他应用打开」与分享入口，无需自建预览器；沙箱内文件经 fileUri 转授权给预览服务读取。
  // 预览不可用（格式不支持 / 设备无预览服务）时退回「保存到…」，保证文件始终能取走。
  private async preview(e: FileEntry): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    const ctx: common.UIAbilityContext = await this.context();
    this.busy = true;
    this.busyLabel = t($r('app.string.module_files_opening'));
    const path: string = await this.fetchToCache(c, ctx, e);
    this.busy = false;
    this.busyLabel = '';
    if (path.length === 0) {
      return;
    }
    try {
      await openCachedFilePreview(ctx, path, e.name);
    } catch (err) {
      this.toast(t($r('app.string.module_files_no_preview')));
      await this.saveToPicker(e);
    }
  }

  // 下载到应用缓存目录（失败已提示并返回空串）
  private async fetchToCache(c: QpConnection, ctx: common.UIAbilityContext,
    e: FileEntry): Promise<string> {
    try {
      return writeCacheFile(ctx, e.name, await fetchWorkspaceFile(c, e));
    } catch (err) {
      this.toast((err as Error).message);
      return '';
    }
  }

  // 「保存到…」：系统保存对话框选位置落盘（非文本文件的长按菜单与预览回退都走这里）
  private async saveToPicker(e: FileEntry): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    const ctx: common.UIAbilityContext = await this.context();
    this.busy = true;
    this.busyLabel = t($r('app.string.module_files_downloading'));
    try {
      const path: string = await this.fetchToCache(c, ctx, e);
      if (path.length === 0) {
        return;
      }
      const saved: boolean = await saveCachedFileWithPicker(ctx, path, e.name);
      if (saved) {
        this.toast(t($r('app.string.module_files_downloaded')));
      }
    } catch (err) {
      this.toast((err as Error).message);
    } finally {
      this.busy = false;
      this.busyLabel = '';
    }
  }

  private async upload(): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    const ctx: common.UIAbilityContext = await this.context();
    let picked: PickedFile[] = [];
    try {
      // 上传到工作空间按原文件名落盘（同名由服务端 conflict=rename 处理），不加时间戳前缀
      picked = await pickFiles(ctx, false);
    } catch (err) {
      this.toast((err as Error).message);
      return;
    }
    if (picked.length === 0) {
      return;
    }
    this.busy = true;
    try {
      await uploadWorkspaceFiles(c, this.dirPath, picked);
      await this.load();
    } catch (err) {
      this.toast((err as Error).message);
    } finally {
      for (const f of picked) {
        removeTemp(f.path);
      }
      this.busy = false;
    }
  }

  private async save(): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      // 原先静默 return：点保存"完全没反应"即由此而来（未连接时应给出提示）
      this.toast(t($r('app.string.wb_not_connected')));
      return;
    }
    const target: string = this.draftPath.trim();
    if (target.length === 0) {
      this.toast(t($r('app.string.module_files_path_label')));
      return;
    }
    this.busy = true;
    try {
      const body: Record<string, string> = { 'content': this.draftText };
      const url: string = `${c.baseUrl}/api/workspace/file-content?path=${encodeURIComponent(target)}`
        + `&root=workspace`;
      const resp: http.HttpResponse = await doRequest(url, http.RequestMethod.PUT,
        JSON.stringify(body), c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(tf($r('app.string.module_files_save_failed'), resp.responseCode));
      }
      this.toast(t($r('app.string.module_files_saved')));
      this.closeSheet();
      await this.load();
    } catch (err) {
      this.toast((err as Error).message);
    } finally {
      this.busy = false;
    }
  }

  private goUp(): void {
    const parts: string[] = this.dirPath.split('/');
    const kept: string[] = [];
    for (let i = 0; i < parts.length; i++) {
      if (parts[i].length > 0) {
        kept.push(parts[i]);
      }
    }
    kept.pop();
    this.dirPath = kept.join('/');
    this.loaded = false;
    this.load();
  }

  private newFile(): void {
    const name: string = 'untitled.md';
    this.openEditor(this.dirPath.length > 0 ? `${this.dirPath}/${name}` : name, '');
  }

  private iconOf(e: FileEntry): Resource {
    if (e.kind === 'directory') {
      return $r('app.media.folder');
    }
    return e.previewKind === 'text' || e.previewKind === 'csv'
      ? $r('app.media.file_text') : $r('app.media.file_text');
  }

  // 长按菜单的选项：统一材质出口 + 收起时复位长按判据（保证下次长按是真实边沿）
  private fileMenuOptions(e: FileEntry): ContextMenuOptions {
    const opts: ContextMenuOptions = contextMenuOptions();
    opts.aboutToDisappear = (): void => {
      if (this.menuPath === e.path) {
        this.menuPath = '';
      }
    };
    return opts;
  }

  // 清单行（窄屏形态）：文本文件点开进编辑面板，其余类型点开交给系统预览服务；
  // 只有文件夹给"进入下一级"箭头（点开 = 整页进该目录）
  @Builder
  entryRow(e: FileEntry) {
    IosRow({
      icon: this.iconOf(e),
      label: e.name,
      subtitle: e.kind === 'directory' ? t($r('app.string.module_files_folder'))
        : (sizeLabel(e.size).length > 0 ? sizeLabel(e.size)
          : t($r('app.string.module_files_file'))),
      tappable: !this.busy,
      showChevron: e.kind === 'directory',
      onPress: (): void => {
        this.openEntry(e);
      }
    })
  }

  // 文件树行（宽屏横排形态）：层级缩进 + 引导线 + 展开箭头，点文件夹原地展开、不换页
  @Builder
  treeRow(r: TreeRow) {
    FileTreeRow({
      name: r.entry.name,
      icon: this.iconOf(r.entry),
      isDir: r.entry.kind === 'directory',
      sizeText: r.entry.kind === 'directory' ? '' : sizeLabel(r.entry.size),
      depth: r.depth,
      expanded: r.expanded,
      tappable: !this.busy,
      onPress: (): void => {
        this.openEntry(r.entry);
      }
    })
  }

  @Builder
  fileMenu(e: FileEntry) {
    Menu() {
      MenuItem({ content: t($r('app.string.module_files_save_as')) })
        .onClick((): void => {
          this.saveToPicker(e);
        })
    }
  }

  @Builder
  sheetContent() {
    Column() {
      Text(this.sheetEdit
        ? t($r('app.string.module_files_edit_title'))
        : t($r('app.string.module_files_preview_title')))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ bottom: 12 })

      if (this.sheetEdit) {
        Text(t($r('app.string.module_files_path_label')))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
          .width('100%')
          .margin({ bottom: 6 })
        // 输入框与状态双向绑定（官方 TextArea/TextInput 说明：text 参数建议与状态实时绑定，
        // 否则组件刷新时组件内文本会与状态脱节——半模态面板复用节点，二次打开就会残留上次内容）
        TextInput({ text: $$this.draftPath })
          .width('100%')
          .height(46)
          .fontSize(UiTokens.fsBody)
          .backgroundColor($r('app.color.sheet_card_bg'))
          .borderRadius(UiTokens.cardRadius)
      }

      if (this.mdRendered) {
        Scroll() {
          Column() {
            Markdown({ content: this.draftText, options: { darkMode: this.dark } })
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.sheet_card_bg'))
        }
        .width('100%')
        .layoutWeight(1)
        .align(Alignment.Top)
        .scrollBar(BarState.Auto)
      } else if (this.sheetEdit) {
        TextArea({ text: $$this.draftText })
          .width('100%')
          .layoutWeight(1)
          .margin({ top: 10 })
          .fontSize(UiTokens.fsSecondary)
          .lineHeight(20)
          .backgroundColor($r('app.color.sheet_card_bg'))
          .borderRadius(UiTokens.cardRadius)
      } else {
        Scroll() {
          Text(this.draftText)
            .fontSize(UiTokens.fsSecondary)
            .lineHeight(20)
            .width('100%')
            .padding(UiTokens.cardPad)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.sheet_card_bg'))
            .textAlign(TextAlign.Start)
            .wordBreak(WordBreak.BREAK_ALL)
            .copyOption(CopyOptions.LocalDevice)
        }
        .width('100%')
        .layoutWeight(1)
        .align(Alignment.Top)
        .scrollBar(BarState.Auto)
      }

      Row() {
        if (this.mdRendered) {
          // 渲染预览态：编辑（切纯文本） / 确认（关闭）
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_edit'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .layoutWeight(1)
          .height(46)
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((isOn: boolean): void => {
            if (isOn) {
              this.mdRendered = false;
              this.sheetEdit = true;
            }
          })
          // 其他应用打开（md 预览态；交给系统隐式 Want）
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.module_files_open_external'))
              .fontSize(UiTokens.fsSecondary)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((isOn: boolean): void => {
            if (isOn) {
              this.openExternally();
            }
          })
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_confirm'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((): void => {
            this.closeSheet();
          })
        } else if (this.sheetEdit) {
          // 取消：Toggle 外壳 + 沉浸材质（内容区 Button 直接挂材质是空转；Toggle 在豁免名单内）
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_cancel'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .layoutWeight(1)
          .height(46)
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((): void => {
            this.closeSheet();
          })
          // 另存为…（系统 picker 可选目录；与「保存」= 写回工作区原路径区分）
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.module_files_save_as'))
              .fontSize(UiTokens.fsSecondary)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((isOn: boolean): void => {
            if (isOn) {
              this.saveAsLocal();
            }
          })
          // 保存：同上，主色文案；busy 时降为不透明混色并拦截点击
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text(this.busy ? t($r('app.string.module_files_saving'))
              : t($r('app.string.common_save')))
              .fontSize(UiTokens.fsBody)
              .fontColor(this.busy ? $r('app.color.btn_gray_text') : Color.White)
          }
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .padding(0)
          .backgroundColor(this.busy ? $r('app.color.card_bg') : accentColor(this.dark))
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((): void => {
            if (!this.busy) {
              this.save();
            }
          })
        } else {
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_confirm'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.btn_gray_text'))
          }
          .width('100%')
          .height(46)
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.sheetBtnMaterial)
          .onChange((): void => {
            this.closeSheet();
          })
        }
      }
      .width('100%')
      .margin({ top: 12 })
    }
    .width('100%')
    .height('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度，避免与标题重叠
    .padding({ left: 20, right: 20, top: 64, bottom: 16 })
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(t($r('app.string.module_files_loading')))
      } else {
        IosGroup({ title: this.dirPath.length > 0 ? this.dirPath
          : t($r('app.string.module_files_root')) }) {
          if (this.dirPath.length > 0) {
            IosRow({
              icon: $r('app.media.chevron_left'),
              label: t($r('app.string.module_files_up')),
              tappable: true,
              onPress: (): void => {
                this.goUp();
              }
            })
          }
          IosRow({
            icon: $r('app.media.arrow_up_to_line'),
            label: this.busy && this.busyLabel.length > 0 ? this.busyLabel
              : (this.busy ? t($r('app.string.module_files_uploading'))
                : t($r('app.string.module_files_upload'))),
            subtitle: t($r('app.string.module_files_upload_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.upload();
            }
          })
          IosRow({
            icon: $r('app.media.file_pen'),
            label: t($r('app.string.module_files_new')),
            subtitle: t($r('app.string.module_files_new_hint')),
            tappable: true,
            onPress: (): void => {
              this.newFile();
            }
          })
          if (this.wide) {
            // 宽屏横排：树形呈现（层级缩进 + 展开/收起箭头），点文件夹不再换页
            ForEach(this.treeRows, (r: TreeRow) => {
              if (r.entry.kind === 'directory') {
                this.treeRow(r)
              } else {
                Column() {
                  this.treeRow(r)
                }
                .width('100%')
                .bindContextMenu(this.menuPath === r.entry.path, this.fileMenu(r.entry),
                  this.fileMenuOptions(r.entry))
                .gesture(LongPressGesture({ duration: 300 })
                  .onAction((): void => {
                    this.menuPath = r.entry.path;
                  }))
              }
            }, (r: TreeRow) => `${r.entry.path}|${r.expanded ? 1 : 0}|${r.depth}`)
          } else {
          ForEach(this.entries, (e: FileEntry) => {
            if (e.kind === 'directory') {
              this.entryRow(e)
            } else {
              // 长按「保存到…」：文件行外包一层内置容器才能挂长按菜单（自定义组件不能链属性方法）。
              // ResponseType.LongPress 的最短长按时间由系统定死、无参数可调 → 改走 bindContextMenu(isShown)
              // + LongPressGesture(duration: 300)（官方：LongPressGesture 默认 500ms 且 duration 可配），
              // 收起时在 aboutToDisappear 复位，保证下次长按仍是真实的 false→true 边沿。
              Column() {
                this.entryRow(e)
              }
              .width('100%')
              .bindContextMenu(this.menuPath === e.path, this.fileMenu(e), this.fileMenuOptions(e))
              .gesture(LongPressGesture({ duration: 300 })
                .onAction((): void => {
                  this.menuPath = e.path;
                }))
            }
          }, (e: FileEntry) => e.path)
          }
        }
        if (!this.wide && this.entries.length === 0) {
          ModuleEmpty($r('app.media.folder'),
            t($r('app.string.module_files_empty_title')),
            t($r('app.string.module_files_empty_subtitle')))
        }
        ModuleFooter(t($r('app.string.module_files_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetEdit ? 680 : 620, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }
}
