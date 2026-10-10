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
import { picker, fileIo as fs } from '@kit.CoreFileKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { PickedFile, pickFiles, removeTemp } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { UiTokens } from '../theme/UiTokens';
import { isDarkMode, accentColor } from '../theme/Accent';

const TREE_LIMIT: number = 200;
const CHUNK_LIMIT: number = 256 * 1024;

class FileEntry {
  name: string = '';
  path: string = '';
  kind: string = 'file';        // file | directory
  size: number = -1;            // -1 = 目录（接口返回 null）
  previewKind: string = '';     // text | csv | image | pdf | binary | directory
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
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
  const list: http.MultiFormData[] = [];
  for (const f of files) {
    const item: http.MultiFormData = {
      name: 'files',
      contentType: f.mime,
      remoteFileName: f.name,
      filePath: f.path
    };
    list.push(item);
  }
  const header: Record<string, Object> = authHeader(conn);
  header['Content-Type'] = 'multipart/form-data';
  const options: http.HttpRequestOptions = {
    method: http.RequestMethod.POST,
    header: header,
    multiFormDataList: list,
    connectTimeout: 15000,
    readTimeout: 120000,
    expectDataType: http.HttpDataType.STRING
  };
  const url: string = `${conn.baseUrl}/api/workspace/file-upload?path=`
    + `${encodeURIComponent(dir)}&root=workspace&conflict=rename`;
  const req: http.HttpRequest = http.createHttp();
  try {
    const resp: http.HttpResponse = await req.request(url, options);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`上传失败（HTTP ${resp.responseCode}）。`);
    }
  } finally {
    req.destroy();
  }
}

// 二进制下载 → 系统保存对话框选位置 → 写入（返回值 false = 用户取消保存）
async function downloadWorkspaceFile(conn: QpConnection, entry: FileEntry,
  ctx: common.UIAbilityContext): Promise<boolean> {
  const header: Record<string, Object> = authHeader(conn);
  const options: http.HttpRequestOptions = {
    method: http.RequestMethod.GET,
    header: header,
    connectTimeout: 15000,
    readTimeout: 120000,
    expectDataType: http.HttpDataType.ARRAY_BUFFER
  };
  const url: string = `${conn.baseUrl}/api/workspace/file-download?path=`
    + `${encodeURIComponent(entry.path)}&root=workspace`;
  const req: http.HttpRequest = http.createHttp();
  let buffer: ArrayBuffer | null = null;
  try {
    const resp: http.HttpResponse = await req.request(url, options);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`下载失败（HTTP ${resp.responseCode}）。`);
    }
    buffer = resp.result as ArrayBuffer;
  } finally {
    req.destroy();
  }
  const saveOptions: picker.DocumentSaveOptions = new picker.DocumentSaveOptions();
  saveOptions.newFileNames = [entry.name.length > 0 ? entry.name : 'qwenpaw-file'];
  const view: picker.DocumentViewPicker = new picker.DocumentViewPicker(ctx);
  const uris: string[] = await view.save(saveOptions);
  if (uris.length === 0) {
    return false;
  }
  const file: fs.File = fs.openSync(uris[0], fs.OpenMode.READ_WRITE);
  try {
    if (buffer !== null) {
      fs.writeSync(file.fd, buffer);
    }
  } finally {
    fs.closeSync(file);
  }
  return true;
}

@Component
export struct ModuleFiles {
  @State dirPath: string = '';
  @State entries: FileEntry[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State busyLabel: string = '';
  @State sheetShown: boolean = false;
  @State sheetEdit: boolean = false;      // false = 只读预览，true = 可编辑
  @State draftPath: string = '';
  @State draftText: string = '';
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;
  private dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.dark = isDarkMode(ctx);
    this.load();
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async context(): Promise<common.UIAbilityContext> {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = await this.context();
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const url: string = `${c.baseUrl}/api/workspace/tree?path=${encodeURIComponent(this.dirPath)}`
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
      this.entries = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
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

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private async openEntry(e: FileEntry): Promise<void> {
    if (e.kind === 'directory') {
      this.dirPath = e.path;
      this.loaded = false;
      await this.load();
      return;
    }
    if (!isTextual(e.previewKind)) {
      await this.download(e);
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
        this.openPreview(e.name, `${content}\n\n[${this.t($r('app.string.module_files_truncated'))}]`);
      } else {
        this.openEditor(e.path, content);
      }
    } catch (err) {
      this.toast((err as Error).message);
    } finally {
      this.busy = false;
    }
  }

  private async download(e: FileEntry): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    const ctx: common.UIAbilityContext = await this.context();
    this.busy = true;
    this.busyLabel = this.t($r('app.string.module_files_downloading'));
    try {
      const saved: boolean = await downloadWorkspaceFile(c, e, ctx);
      if (saved) {
        this.toast(this.t($r('app.string.module_files_downloaded')));
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
      return;
    }
    const target: string = this.draftPath.trim();
    if (target.length === 0) {
      this.toast(this.t($r('app.string.module_files_path_label')));
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
        throw new Error(`保存失败（HTTP ${resp.responseCode}）。`);
      }
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
      return $r('sys.symbol.folder');
    }
    return e.previewKind === 'text' || e.previewKind === 'csv'
      ? $r('sys.symbol.doc_text') : $r('sys.symbol.doc_plaintext');
  }

  @Builder
  sheetContent() {
    Column() {
      Text(this.sheetEdit
        ? this.t($r('app.string.module_files_edit_title'))
        : this.t($r('app.string.module_files_preview_title')))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .width('100%')
        .margin({ bottom: 12 })

      if (this.sheetEdit) {
        Text(this.t($r('app.string.module_files_path_label')))
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

      if (this.sheetEdit) {
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
        if (this.sheetEdit) {
          Button($r('app.string.common_cancel'))
            .layoutWeight(1)
            .height(46)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.btn_gray_text'))
            .stateEffect(false)
            .onClick((): void => {
              this.closeSheet();
            })
          Button(this.busy ? this.t($r('app.string.module_files_saving'))
            : this.t($r('app.string.common_save')))
            .layoutWeight(1)
            .height(46)
            .margin({ left: 10 })
            .backgroundColor(accentColor(this.dark))
            .fontColor(Color.White)
            .stateEffect(false)
            .enabled(!this.busy)
            .onClick((): void => {
              this.save();
            })
        } else {
          Button($r('app.string.common_confirm'))
            .width('100%')
            .height(46)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.btn_gray_text'))
            .stateEffect(false)
            .onClick((): void => {
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
        ModuleLoading(this.t($r('app.string.module_files_loading')))
      } else {
        IosGroup({ title: this.dirPath.length > 0 ? this.dirPath
          : this.t($r('app.string.module_files_root')) }) {
          if (this.dirPath.length > 0) {
            IosRow({
              icon: $r('sys.symbol.chevron_left'),
              label: this.t($r('app.string.module_files_up')),
              tappable: true,
              onPress: (): void => {
                this.goUp();
              }
            })
          }
          IosRow({
            icon: $r('sys.symbol.arrow_up_to_line'),
            label: this.busy && this.busyLabel.length > 0 ? this.busyLabel
              : (this.busy ? this.t($r('app.string.module_files_uploading'))
                : this.t($r('app.string.module_files_upload'))),
            subtitle: this.t($r('app.string.module_files_upload_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.upload();
            }
          })
          IosRow({
            icon: $r('sys.symbol.doc_plaintext_and_pencil'),
            label: this.t($r('app.string.module_files_new')),
            subtitle: this.t($r('app.string.module_files_new_hint')),
            tappable: true,
            onPress: (): void => {
              this.newFile();
            }
          })
          ForEach(this.entries, (e: FileEntry) => {
            IosRow({
              icon: this.iconOf(e),
              label: e.name,
              subtitle: e.kind === 'directory' ? this.t($r('app.string.module_files_folder'))
                : (sizeLabel(e.size).length > 0 ? sizeLabel(e.size)
                  : this.t($r('app.string.module_files_file'))),
              tappable: !this.busy,
              onPress: (): void => {
                this.openEntry(e);
              }
            })
          }, (e: FileEntry) => e.path)
        }
        if (this.entries.length === 0) {
          ModuleEmpty($r('sys.symbol.folder'),
            this.t($r('app.string.module_files_empty_title')),
            this.t($r('app.string.module_files_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_files_footer')))
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
