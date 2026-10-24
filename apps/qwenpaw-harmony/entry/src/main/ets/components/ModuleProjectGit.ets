/*
 * 工作台模块 · Coding 项目与 Git —— 对齐 PR #7378 features/workbench/ProjectGitSettings.tsx。
 *   项目目录：GET/PUT /api/workspace/project-directory（PUT {path} 切换，{path:null} 恢复默认）
 *             GET  /api/workspace/project-directory/list
 *             POST /api/workspace/project-directory/create {name}
 *             POST /api/workspace/project-directory/upload-zip?name=  （multipart 字段 file）
 *   Coding 模式：GET/POST /api/coding-mode {enabled}
 *   Git：GET /api/workspace/git/status | log?limit=20
 *        POST /api/workspace/git/{stage|unstage|discard} {paths:[..]}、commit {message}
 *             /checkout {branch,create}、revert {commit_hash}
 * 半模态统一件：表单（新建项目 / 分支 / 提交说明）走 FieldSheet，变更与提交流水操作走 OptionsSheet，
 * 两者挂在同一张半模态里按模式切换（同一组件挂多个 bindSheet 只有最后一个生效）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { atlsRequest, buildMultipart, MultipartBody } from '../services/AtlsTransport';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { PickedFile, pickSingleFile, removeTemp } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { t } from '../services/I18n';

class ProjectInfo {
  path: string = '';
  name: string = '';
  isDefault: boolean = false;
}

class ProjectListItem {
  path: string = '';
  name: string = '';
  isGit: boolean = false;
  isActive: boolean = false;
}

class GitChange {
  path: string = '';
  status: string = '';
  staged: boolean = false;
}

class CommitInfo {
  hash: string = '';
  author: string = '';
  date: string = '';
  message: string = '';
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

function boolOf(value: Object): boolean {
  return value === true;
}

// 半模态模式：表单（FieldSheet）/ 操作菜单（OptionsSheet）
const MODE_NONE: string = '';
const MODE_PROJECT: string = 'project';
const MODE_IMPORT: string = 'import';
const MODE_BRANCH: string = 'branch';
const MODE_COMMIT: string = 'commit';
const MODE_CHANGE: string = 'change';
const MODE_LOG: string = 'log';

@Component
export struct ModuleProjectGit {
  @State project: ProjectInfo | null = null;
  @State projects: ProjectListItem[] = [];
  @State coding: boolean = false;
  @State hasGit: boolean = false;
  @State branch: string = '';
  @State ahead: number = 0;
  @State behind: number = 0;
  @State changes: GitChange[] = [];
  @State commits: CommitInfo[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private change: GitChange = new GitChange();
  private commit: CommitInfo = new CommitInfo();
  private zip: PickedFile | null = null;
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    this.load();
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async request(path: string, method: http.RequestMethod,
    body: string | null): Promise<Record<string, Object> | null> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return null;
    }
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    if (method !== http.RequestMethod.GET) {
      return null;
    }
    const result: Object = resp.result;
    if (typeof result !== 'string' || (result as string).trim().length === 0) {
      return null;
    }
    return jsonOf(resp);
  }

  // 顶层返回数组的端点（项目列表 / git log）：jsonOf 是对象口径，故单独解析
  private async requestArray(path: string): Promise<Object[] | null> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return null;
    }
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api${path}`,
      http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    const result: Object = resp.result;
    if (typeof result !== 'string') {
      return null;
    }
    try {
      const parsed: Object = JSON.parse(result as string);
      return Array.isArray(parsed) ? parsed as Object[] : null;
    } catch (e) {
      return null;
    }
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const dir: Record<string, Object> | null = await this.request(
        '/workspace/project-directory', http.RequestMethod.GET, null);
      if (dir !== null) {
        const p: ProjectInfo = new ProjectInfo();
        p.path = strOf(dir['path'], '');
        p.name = strOf(dir['name'], '');
        p.isDefault = boolOf(dir['is_workspace_default']);
        this.project = p;
      }
      const codingRes: Record<string, Object> | null = await this.request(
        '/coding-mode', http.RequestMethod.GET, null);
      this.coding = codingRes !== null && boolOf(codingRes['enabled']);

      const list: Object[] | null = await this.requestArray('/workspace/project-directory/list');
      this.projects = this.projectListOf(list);

      const status: Record<string, Object> | null = await this.request(
        '/workspace/git/status', http.RequestMethod.GET, null);
      if (status !== null) {
        this.hasGit = true;
        this.branch = strOf(status['branch'], '');
        const ahead: Object = status['ahead'];
        const behind: Object = status['behind'];
        this.ahead = typeof ahead === 'number' ? ahead as number : 0;
        this.behind = typeof behind === 'number' ? behind as number : 0;
        this.changes = this.changesOf(status['changes']);
      } else {
        this.hasGit = false;
        this.branch = '';
        this.changes = [];
      }
      const log: Object[] | null = await this.requestArray('/workspace/git/log?limit=20');
      this.commits = this.commitsOf(log);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private projectListOf(value: Object[] | null): ProjectListItem[] {
    const out: ProjectListItem[] = [];
    if (value === null) {
      return out;
    }
    for (const item of value) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const p: ProjectListItem = new ProjectListItem();
      p.path = strOf(r['path'], '');
      p.name = strOf(r['name'], '');
      p.isGit = boolOf(r['is_git']);
      p.isActive = boolOf(r['is_active']);
      out.push(p);
    }
    return out;
  }

  private changesOf(value: Object): GitChange[] {
    const out: GitChange[] = [];
    if (!Array.isArray(value)) {
      return out;
    }
    for (const item of value as Object[]) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const c: GitChange = new GitChange();
      c.path = strOf(r['path'], '');
      c.status = strOf(r['status'], '');
      c.staged = boolOf(r['staged']);
      out.push(c);
    }
    return out;
  }

  private commitsOf(value: Object[] | null): CommitInfo[] {
    const out: CommitInfo[] = [];
    if (value === null) {
      return out;
    }
    for (const item of value) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const k: CommitInfo = new CommitInfo();
      k.hash = strOf(r['hash'], '');
      k.author = strOf(r['author'], '');
      k.date = strOf(r['date'], '');
      k.message = strOf(r['message'], '');
      out.push(k);
    }
    return out;
  }

  private async run(path: string, body: Record<string, Object>,
    success: string = ''): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.request(path, http.RequestMethod.POST, JSON.stringify(body));
      await this.load();
      if (success.length > 0) {
        this.toast(success);
      }
    } catch (e) {
      this.toast(`${t($r('app.string.module_git_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async openSheet(mode: string): Promise<void> {
    this.sheetMode = mode;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private async toggleCoding(enabled: boolean): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.request('/coding-mode', http.RequestMethod.POST,
        JSON.stringify({ 'enabled': enabled }));
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_git_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async pickZip(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    try {
      const picked: PickedFile | null = await pickSingleFile(ctx, ['.zip']);
      if (picked === null) {
        return;
      }
      this.zip = picked;
      await this.openSheet(MODE_IMPORT);
    } catch (e) {
      this.toast((e as Error).message);
    }
  }

  // 表单保存：新建项目 / 导入 ZIP / 切换分支 / 创建 Commit
  private async saveForm(values: Record<string, Object>): Promise<void> {
    if (this.sheetMode === MODE_PROJECT) {
      await this.request('/workspace/project-directory/create', http.RequestMethod.POST,
        JSON.stringify({ 'name': strOf(values['name'], '').trim() }));
      await this.load();
      return;
    }
    if (this.sheetMode === MODE_IMPORT) {
      const zip: PickedFile | null = this.zip;
      if (zip === null) {
        throw new Error(t($r('app.string.module_git_zip_missing')));
      }
      await this.uploadZip(strOf(values['name'], '').trim(), zip);
      removeTemp(zip.path);
      this.zip = null;
      await this.load();
      return;
    }
    if (this.sheetMode === MODE_BRANCH) {
      await this.request('/workspace/git/checkout', http.RequestMethod.POST,
        JSON.stringify({
          'branch': strOf(values['branch'], '').trim(),
          'create': values['create'] === true
        }));
      await this.load();
      return;
    }
    await this.request('/workspace/git/commit', http.RequestMethod.POST,
      JSON.stringify({ 'message': strOf(values['message'], '').trim() }));
    await this.load();
  }

  private async uploadZip(name: string, zip: PickedFile): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    const multipart: MultipartBody = buildMultipart([{
      name: 'file',
      filePath: zip.path,
      fileName: zip.name,
      contentType: 'application/zip'
    }]);
    const header: Record<string, Object> = {
      'Content-Type': multipart.contentType,
      'Accept': 'application/json'
    };
    if (c.token.length > 0) {
      header['Authorization'] = `Bearer ${c.token}`;
    }
    if (c.agentId.length > 0) {
      header['X-Agent-Id'] = c.agentId;
    }
    const url: string = `${c.baseUrl}/api/workspace/project-directory/upload-zip`
      + `?name=${encodeURIComponent(name)}`;
    const resp: http.HttpResponse = await atlsRequest({
      url: url,
      method: http.RequestMethod.POST,
      header: header,
      bodyBytes: multipart.body,
      connectMs: 15000,
      readMs: 300000
    });
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
  }

  // 变更行操作：暂存 / 取消暂存 / 丢弃（对齐 7378 openChange 的 ActionSheet）
  private changeOptions(): SheetOption[] {
    const out: SheetOption[] = [];
    if (this.change.staged) {
      out.push(optionOf('unstage', t($r('app.string.module_git_act_unstage'))));
    } else {
      out.push(optionOf('stage', t($r('app.string.module_git_act_stage'))));
      out.push(optionOf('discard', t($r('app.string.module_git_act_discard'))));
    }
    return out;
  }

  private logOptions(): SheetOption[] {
    return [optionOf('revert', t($r('app.string.module_git_act_revert')))];
  }

  private async onAction(value: string): Promise<void> {
    const path: string = this.change.path;
    const hash: string = this.commit.hash;
    if (value === 'unstage') {
      await this.run('/workspace/git/unstage', { 'paths': [path] });
    } else if (value === 'stage') {
      await this.run('/workspace/git/stage', { 'paths': [path] });
    } else if (value === 'discard') {
      await this.run('/workspace/git/discard', { 'paths': [path] });
    } else if (value === 'revert') {
      await this.run('/workspace/git/revert', { 'commit_hash': hash },
        t($r('app.string.module_git_reverted')));
    }
  }

  private formDefs(): FieldDef[] {
    if (this.sheetMode === MODE_PROJECT) {
      return [fieldDef('name', t($r('app.string.module_git_field_name')), 'text', true)];
    }
    if (this.sheetMode === MODE_BRANCH) {
      return [
        fieldDef('branch', t($r('app.string.module_git_field_branch')), 'text', true),
        fieldDef('create', t($r('app.string.module_git_field_create')), 'boolean')
      ];
    }
    return [fieldDef('message', t($r('app.string.module_git_field_message')), 'textarea', true)];
  }

  private formTitle(): string {
    if (this.sheetMode === MODE_PROJECT) {
      return t($r('app.string.module_git_title_project'));
    }
    if (this.sheetMode === MODE_IMPORT) {
      return t($r('app.string.module_git_title_import'));
    }
    if (this.sheetMode === MODE_BRANCH) {
      return t($r('app.string.module_git_title_branch'));
    }
    return t($r('app.string.module_git_title_commit'));
  }

  private formInitial(): Record<string, Object> {
    if (this.sheetMode === MODE_IMPORT) {
      const zip: PickedFile | null = this.zip;
      const raw: string = zip !== null ? zip.name : '';
      const name: string = raw.toLowerCase().endsWith('.zip') ? raw.substring(0, raw.length - 4) : raw;
      const out: Record<string, Object> = {};
      out['name'] = name;
      return out;
    }
    if (this.sheetMode === MODE_BRANCH) {
      const out: Record<string, Object> = {};
      out['branch'] = this.branch;
      return out;
    }
    return {};
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_CHANGE) {
        OptionsSheet({
          title: this.change.path,
          options: this.changeOptions(),
          current: '',
          onPick: (v: string): void => {
            this.onAction(v);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.sheetMode === MODE_LOG) {
        OptionsSheet({
          title: this.commit.message,
          options: this.logOptions(),
          current: '',
          onPick: (v: string): void => {
            this.onAction(v);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else {
        FieldSheet({
          title: this.formTitle(),
          defs: this.formDefs(),
          initial: this.formInitial(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveForm(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      }
    }
    .width('100%')
    .height('100%')
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(t($r('app.string.module_loading')))
      } else {
        IosGroup({ title: t($r('app.string.module_git_group')) }) {
          IosRow({
            icon: $r('app.media.square_code'),
            label: t($r('app.string.module_git_coding')),
            subtitle: t($r('app.string.module_git_coding_hint')),
            hasSwitch: true,
            switchOn: this.coding,
            onSwitch: (on: boolean): void => {
              this.toggleCoding(on);
            }
          })
          if (this.project !== null) {
            IosRow({
              icon: $r('app.media.folder'),
              label: this.project!.name.length > 0 ? this.project!.name
                : t($r('app.string.module_git_workspace')),
              subtitle: this.project!.path,
              trailing: this.project!.isDefault ? t($r('app.string.module_git_default'))
                : t($r('app.string.module_git_current'))
            })
          }
          IosRow({
            icon: $r('app.media.folder_plus'),
            label: t($r('app.string.module_git_new')),
            subtitle: t($r('app.string.module_git_new_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_PROJECT);
            }
          })
          IosRow({
            icon: $r('app.media.arrow_up_to_line'),
            label: t($r('app.string.module_git_import')),
            tappable: !this.busy,
            onPress: (): void => {
              this.pickZip();
            }
          })
          if (this.project !== null && !this.project!.isDefault) {
            IosRow({
              icon: $r('app.media.rotate_ccw'),
              label: t($r('app.string.module_git_restore')),
              tappable: !this.busy,
              onPress: (): void => {
                // 恢复默认：服务端口径为 path=null（None 表示回默认 workspace）
                this.restoreDefault();
              }
            })
          }
        }

        if (this.projects.length > 0) {
          IosGroup({ title: `${t($r('app.string.module_git_projects'))} · ${this.projects.length}` }) {
            ForEach(this.projects, (p: ProjectListItem) => {
              IosRow({
                icon: p.isActive ? $r('app.media.check') : $r('app.media.folder'),
                label: p.name,
                subtitle: p.isGit ? t($r('app.string.module_git_is_git')) : p.path,
                trailing: p.isActive ? t($r('app.string.module_git_current')) : '',
                tappable: !p.isActive && !this.busy,
                onPress: (): void => {
                  this.switchProject(p);
                }
              })
            }, (p: ProjectListItem) => p.path)
          }
        }

        if (this.hasGit) {
          IosGroup({ title: t($r('app.string.module_git_git')) }) {
            IosRow({
              icon: $r('app.media.arrow_left_right'),
              label: this.branch.length > 0 ? this.branch
                : t($r('app.string.module_git_branch_unnamed')),
              subtitle: `ahead ${this.ahead} · behind ${this.behind}`,
              trailing: `${this.changes.length} ${t($r('app.string.module_git_changes'))}`,
              tappable: !this.busy,
              onPress: (): void => {
                this.openSheet(MODE_BRANCH);
              }
            })
            IosRow({
              icon: $r('app.media.circle_check'),
              label: t($r('app.string.module_git_commit_staged')),
              subtitle: t($r('app.string.module_git_commit_hint')),
              tappable: !this.busy,
              onPress: (): void => {
                this.openSheet(MODE_COMMIT);
              }
            })
            ForEach(this.changes, (c: GitChange) => {
              IosRow({
                icon: $r('app.media.file_diff'),
                label: c.path,
                subtitle: c.status,
                trailing: c.staged ? t($r('app.string.module_git_staged'))
                  : t($r('app.string.module_git_unstaged')),
                tappable: !this.busy,
                onPress: (): void => {
                  this.change = c;
                  this.openSheet(MODE_CHANGE);
                }
              })
            }, (c: GitChange) => `${c.staged}:${c.path}`)
          }
          if (this.commits.length > 0) {
            IosGroup({ title: t($r('app.string.module_git_recent')) }) {
              ForEach(this.commits, (k: CommitInfo) => {
                IosRow({
                  icon: $r('app.media.circle_check'),
                  label: k.message,
                  subtitle: `${k.author} · ${k.date}`,
                  trailing: k.hash.length > 7 ? k.hash.substring(0, 7) : k.hash,
                  tappable: !this.busy,
                  onPress: (): void => {
                    this.commit = k;
                    this.openSheet(MODE_LOG);
                  }
                })
              }, (k: CommitInfo) => k.hash)
            }
          }
        } else {
          ModuleEmpty($r('app.media.arrow_left_right'),
            t($r('app.string.module_git_not_repo_title')),
            t($r('app.string.module_git_not_repo_subtitle')))
        }
        ModuleFooter(t($r('app.string.module_git_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_COMMIT || this.sheetMode === MODE_IMPORT ? 560 : 480,
        this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  private async switchProject(p: ProjectListItem): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.request('/workspace/project-directory', http.RequestMethod.PUT,
        JSON.stringify({ 'path': p.path }));
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_git_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async restoreDefault(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.request('/workspace/project-directory', http.RequestMethod.PUT, '{"path":null}');
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_git_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }
}
