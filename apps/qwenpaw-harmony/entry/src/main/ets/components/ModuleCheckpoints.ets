/*
 * 工作台模块 · Checkpoints —— 对齐 PR #7378 features/workbench/CheckpointSettings.tsx。
 *   GET   /api/workspace/checkpoints/status            { auto_enabled, has_checkpoints, workspace_dir }
 *   GET   /api/workspace/checkpoints/graph?limit=100   版本图（nodes / sessions / summary）
 *   GET   /api/workspace/checkpoints/gc/settings       保留策略
 *   PATCH /api/workspace/checkpoints/auto              { enabled } 自动版本开关
 *   POST  /api/workspace/checkpoints/snapshot          手动快照（关联会话）
 *   POST  /api/workspace/checkpoints/restore/preview   恢复预检；/restore 执行恢复
 *   POST  /api/workspace/checkpoints/gc/preview        清理预检；/gc 执行清理
 *   PATCH /api/workspace/checkpoints/gc/settings       保留策略保存
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';

function recOf(value: Object): Record<string, Object> {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, Object>;
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

function numOf(value: Object, fallback: number): number {
  const n: number = Number(value !== undefined && value !== null ? value : fallback);
  return Number.isFinite(n) ? n : fallback;
}

class CpNode {
  key: string = '';
  commit: string = '';
  sha: string = '';
  kind: string = '';
  name: string = '';
  subject: string = '';
  sessionId: string = '';
  sessionTitle: string = '';
  userId: string = '';
  channel: string = '';
  timestampMs: number = 0;
}

class CpSession {
  sessionId: string = '';
  userId: string = '';
  channel: string = '';
  title: string = '';
  archived: boolean = false;
}

@Component
export struct ModuleCheckpoints {
  @State autoEnabled: boolean = false;
  @State workspaceDir: string = '';
  @State nodes: CpNode[] = [];
  @State total: number = 0;
  @State gcCount: number = 0;
  @State gcDays: number = 0;
  @State gcPreDays: number = 0;
  @State loaded: boolean = false;
  @State error: string = '';
  @State gcSheetShown: boolean = false;
  // 半模态单向绑定（不用 $$）：框架回退动画结束时会回写 isShow，会把随后打开的新面板关掉
  private gate: SheetGate = new SheetGate();

  private openGcSheet(): void {
    if (!this.gate.request()) {
      return;
    }
    this.gcSheetShown = true;
  }

  private closeGcSheet(): void {
    this.gate.beginClose();
    this.gcSheetShown = false;
  }

  private sessions: CpSession[] = [];
  private conn: QpConnection | null = null;
  private busy: boolean = false;

  aboutToAppear(): void {
    this.load();
  }

  private async connect(): Promise<QpConnection | null> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadConnection(ctx);
  }

  private async getJson(path: string): Promise<Record<string, Object>> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private async mutate(method: http.RequestMethod, path: string,
    body: string | null): Promise<Record<string, Object>> {
    const c: QpConnection = this.conn as QpConnection;
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      method, body, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private async load(): Promise<void> {
    const c: QpConnection | null = await this.connect();
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const status: Record<string, Object> = await this.getJson('/api/workspace/checkpoints/status');
      const graph: Record<string, Object> = await this.getJson('/api/workspace/checkpoints/graph?limit=100');
      const gc: Record<string, Object> = await this.getJson('/api/workspace/checkpoints/gc/settings');
      this.applyStatus(status);
      this.applyGraph(graph);
      this.applyGc(gc);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private applyStatus(status: Record<string, Object>): void {
    this.autoEnabled = status['auto_enabled'] === true;
    this.workspaceDir = strOf(status['workspace_dir'], '');
  }

  private applyGraph(graph: Record<string, Object>): void {
    const nodes: CpNode[] = [];
    const rawNodes: Object = graph['nodes'];
    if (Array.isArray(rawNodes)) {
      for (const item of rawNodes as Object[]) {
        const rec: Record<string, Object> = recOf(item);
        const node: CpNode = new CpNode();
        node.commit = strOf(rec['commit'], '');
        node.sha = strOf(rec['sha'], '');
        node.kind = strOf(rec['kind'], '');
        node.name = strOf(rec['name'], '');
        node.subject = strOf(rec['subject'], '');
        node.sessionId = strOf(rec['session_id'], '');
        node.sessionTitle = strOf(rec['session_title'], '');
        node.userId = strOf(rec['user_id'], '');
        node.channel = strOf(rec['channel'], '');
        node.timestampMs = numOf(rec['timestamp_ms'], 0);
        node.key = `${node.commit}-${node.timestampMs}`;
        nodes.push(node);
      }
    }
    this.nodes = nodes;
    const summary: Record<string, Object> = recOf(graph['summary']);
    this.total = numOf(summary['total'], nodes.length);
    const sessions: CpSession[] = [];
    const rawSessions: Object = graph['sessions'];
    if (Array.isArray(rawSessions)) {
      for (const item of rawSessions as Object[]) {
        const rec: Record<string, Object> = recOf(item);
        const s: CpSession = new CpSession();
        s.sessionId = strOf(rec['session_id'], '');
        s.userId = strOf(rec['user_id'], '');
        s.channel = strOf(rec['channel'], '');
        s.title = strOf(rec['title'], '');
        s.archived = rec['archived'] === true;
        sessions.push(s);
      }
    }
    this.sessions = sessions;
  }

  private applyGc(gc: Record<string, Object>): void {
    this.gcCount = numOf(gc['gc_keep_count'], 0);
    this.gcDays = numOf(gc['gc_keep_days'], 0);
    this.gcPreDays = numOf(gc['pre_restore_retention_days'], 0);
  }

  // —— 自动版本开关（乐观更新，失败回滚） ——

  private async setAuto(enabled: boolean): Promise<void> {
    if (this.busy) {
      return;
    }
    const previous: boolean = this.autoEnabled;
    this.autoEnabled = enabled;
    this.busy = true;
    try {
      const body: Record<string, boolean> = { 'enabled': enabled };
      const result: Record<string, Object> = await this.mutate(http.RequestMethod.PATCH,
        '/api/workspace/checkpoints/auto', JSON.stringify(body));
      this.autoEnabled = result['auto_enabled'] === true;
    } catch (e) {
      this.autoEnabled = previous;
      this.alert($r('app.string.module_cp_save_failed'), (e as Error).message);
    } finally {
      this.busy = false;
    }
  }

  // —— 手动快照 ——

  private activeSession(): CpSession | null {
    for (const s of this.sessions) {
      if (!s.archived) {
        return s;
      }
    }
    return this.sessions.length > 0 ? this.sessions[0] : null;
  }

  private confirmSnapshot(): void {
    const s: CpSession | null = this.activeSession();
    if (s === null) {
      this.alert($r('app.string.module_cp_no_session_title'), $r('app.string.module_cp_no_session_msg'));
      return;
    }
    const label: string = s.title.length > 0 ? s.title : s.sessionId;
    this.getUIContext().showAlertDialog({
      title: this.t($r('app.string.module_cp_snap_confirm_title')),
      message: `${this.t($r('app.string.module_cp_snap_link'))}「${label}」。`,
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.module_cp_create')),
        action: (): void => {
          this.createSnapshot(s);
        }
      }
    });
  }

  private async createSnapshot(s: CpSession): Promise<void> {
    const body: Record<string, string> = {
      'session_id': s.sessionId,
      'user_id': s.userId,
      'channel': s.channel,
      'name': `Mobile ${new Date().toLocaleString()}`
    };
    await this.run(async (): Promise<void> => {
      await this.mutate(http.RequestMethod.POST,
        '/api/workspace/checkpoints/snapshot', JSON.stringify(body));
    }, $r('app.string.module_cp_snap_done'));
  }

  // —— 恢复 ——

  private async previewRestore(node: CpNode): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    const body: Record<string, Object> = {
      'commit': node.commit,
      'session_id': node.sessionId,
      'user_id': node.userId,
      'channel': node.channel.length > 0 ? node.channel : 'console',
      'include_memory': false,
      'include_files': false
    };
    const text: string = JSON.stringify(body);
    try {
      await this.mutate(http.RequestMethod.POST,
        '/api/workspace/checkpoints/restore/preview', text);
      this.busy = false;
      this.getUIContext().showAlertDialog({
        title: this.t($r('app.string.module_cp_restore_title')),
        message: this.t($r('app.string.module_cp_restore_msg')),
        primaryButton: {
          value: this.t($r('app.string.common_cancel')),
          action: (): void => {}
        },
        secondaryButton: {
          value: this.t($r('app.string.module_cp_restore')),
          fontColor: $r('app.color.status_error'),
          action: (): void => {
            this.doRestore(text);
          }
        }
      });
    } catch (e) {
      this.busy = false;
      this.alert($r('app.string.module_cp_cannot_restore'), (e as Error).message);
    }
  }

  private async doRestore(body: string): Promise<void> {
    await this.run(async (): Promise<void> => {
      await this.mutate(http.RequestMethod.POST, '/api/workspace/checkpoints/restore', body);
    }, $r('app.string.module_cp_restored'));
  }

  // —— 清理 ——

  private async cleanHistory(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const preview: Record<string, Object> = await this.mutate(http.RequestMethod.POST,
        '/api/workspace/checkpoints/gc/preview', '{}');
      const refs: Object = preview['deleted_refs'];
      const count: number = Array.isArray(refs) ? (refs as Object[]).length : 0;
      this.busy = false;
      if (count === 0) {
        this.alert($r('app.string.module_cp_no_clean_title'),
          $r('app.string.module_cp_no_clean_msg'));
        return;
      }
      this.getUIContext().showAlertDialog({
        title: this.t($r('app.string.module_cp_clean_title')),
        message: `${this.t($r('app.string.module_cp_clean_prefix'))}${count}`
          + `${this.t($r('app.string.module_cp_clean_suffix'))}`,
        primaryButton: {
          value: this.t($r('app.string.common_cancel')),
          action: (): void => {}
        },
        secondaryButton: {
          value: this.t($r('app.string.module_cp_clean_btn')),
          fontColor: $r('app.color.status_error'),
          action: (): void => {
            this.doClean();
          }
        }
      });
    } catch (e) {
      this.busy = false;
      this.alert($r('app.string.module_cp_precheck_failed'), (e as Error).message);
    }
  }

  private async doClean(): Promise<void> {
    await this.run(async (): Promise<void> => {
      await this.mutate(http.RequestMethod.POST, '/api/workspace/checkpoints/gc', '{}');
    }, $r('app.string.module_cp_cleaned'));
  }

  private async run(action: () => Promise<void>, success: Resource): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await action();
      await this.load();
      this.alert(success, '');
    } catch (e) {
      this.alert($r('app.string.module_cp_op_failed'), (e as Error).message);
    } finally {
      this.busy = false;
    }
  }

  // —— 保留策略表单 ——

  private gcDefs(): FieldDef[] {
    return [
      fieldDef('gc_keep_count', this.t($r('app.string.module_cp_f_count')), 'number', true),
      fieldDef('gc_keep_days', this.t($r('app.string.module_cp_f_days')), 'number', true),
      fieldDef('pre_restore_retention_days', this.t($r('app.string.module_cp_f_pre')), 'number', true)
    ];
  }

  private async saveGc(values: Record<string, Object>): Promise<void> {
    const body: Record<string, number> = {
      'gc_keep_count': this.positiveInt(values['gc_keep_count'], $r('app.string.module_cp_l_count')),
      'gc_keep_days': this.positiveInt(values['gc_keep_days'], $r('app.string.module_cp_l_days')),
      'pre_restore_retention_days': this.positiveInt(values['pre_restore_retention_days'],
        $r('app.string.module_cp_l_pre'))
    };
    this.applyGc(await this.mutate(http.RequestMethod.PATCH,
      '/api/workspace/checkpoints/gc/settings', JSON.stringify(body)));
  }

  // 保留策略三项都必须是 > 0 的整数（对齐 7378 positiveInteger）
  private positiveInt(value: Object, label: Resource): number {
    const n: number = numOf(value, 0);
    if (!Number.isInteger(n) || n < 1) {
      throw new Error(`${this.t(label)}${this.t($r('app.string.module_cp_int_invalid'))}`);
    }
    return n;
  }

  private kindLabel(kind: string): string {
    if (kind === 'auto') {
      return this.t($r('app.string.module_cp_kind_auto'));
    }
    if (kind === 'pre-restore') {
      return this.t($r('app.string.module_cp_kind_pre'));
    }
    if (kind === 'snap') {
      return this.t($r('app.string.module_cp_kind_snap'));
    }
    return this.t($r('app.string.module_cp_kind_other'));
  }

  private formatDate(ms: number): string {
    if (ms <= 0) {
      return '';
    }
    return new Date(ms).toLocaleString();
  }

  private shortSha(node: CpNode): string {
    if (node.sha.length > 0) {
      return node.sha;
    }
    return node.commit.length > 8 ? node.commit.substring(0, 8) : node.commit;
  }

  private alert(title: Resource, message: Resource | string): void {
    this.getUIContext().showAlertDialog({
      title: title,
      message: message,
      confirm: {
        value: this.t($r('app.string.common_confirm')),
        action: (): void => {}
      }
    });
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(this.t($r('app.string.module_loading')))
      } else {
        IosGroup({ title: this.t($r('app.string.module_cp_group')) }) {
          IosRow({
            icon: $r('sys.symbol.clock'),
            label: this.t($r('app.string.module_cp_auto')),
            subtitle: this.t($r('app.string.module_cp_auto_hint')),
            hasSwitch: true,
            switchOn: this.autoEnabled,
            onSwitch: (on: boolean): void => {
              this.setAuto(on);
            }
          })
          IosRow({
            icon: $r('sys.symbol.plus'),
            label: this.t($r('app.string.module_cp_snap')),
            subtitle: this.t($r('app.string.module_cp_snap_hint')),
            tappable: true,
            onPress: (): void => {
              this.confirmSnapshot();
            }
          })
          IosRow({
            icon: $r('sys.symbol.gearshape'),
            label: this.t($r('app.string.module_cp_gc_policy')),
            subtitle: `${this.gcCount} / ${this.gcDays} · `
              + `${this.t($r('app.string.module_cp_safe_days'))} ${this.gcPreDays}`,
            tappable: true,
            onPress: (): void => {
              this.openGcSheet();
            }
          })
          IosRow({
            icon: $r('sys.symbol.trash'),
            label: this.t($r('app.string.module_cp_clean')),
            subtitle: this.t($r('app.string.module_cp_clean_hint')),
            destructive: true,
            tappable: true,
            onPress: (): void => {
              this.cleanHistory();
            }
          })
        }
        if (this.nodes.length > 0) {
          IosGroup({ title: `${this.t($r('app.string.module_cp_history'))} · ${this.total}` }) {
            ForEach(this.nodes.slice(0, 30), (node: CpNode) => {
              IosRow({
                icon: node.kind === 'snap' ? $r('sys.symbol.plus') : $r('sys.symbol.clock'),
                label: node.name.length > 0 ? node.name
                  : (node.subject.length > 0 ? node.subject : this.kindLabel(node.kind)),
                subtitle: `${node.sessionTitle.length > 0 ? node.sessionTitle : node.sessionId}`
                  + ` · ${this.formatDate(node.timestampMs)}`,
                trailing: this.shortSha(node),
                tappable: true,
                onPress: (): void => {
                  this.previewRestore(node);
                }
              })
            }, (node: CpNode) => node.key)
          }
        } else {
          ModuleEmpty($r('sys.symbol.clock'),
            this.t($r('app.string.module_cp_empty_title')),
            this.t($r('app.string.module_cp_empty_copy')))
        }
        ModuleFooter(this.workspaceDir)
      }
    }
    .width('100%')
    .bindSheet(this.gcSheetShown, this.gcSheet(),
      moduleSheetOptions(420, this.gate,
        (v: boolean): void => {
          this.gcSheetShown = v;
        }))
  }

  @Builder
  gcSheet() {
    Column() {
      FieldSheet({
        title: this.t($r('app.string.module_cp_gc_policy')),
        defs: this.gcDefs(),
        initial: {
          'gc_keep_count': this.gcCount,
          'gc_keep_days': this.gcDays,
          'pre_restore_retention_days': this.gcPreDays
        },
        onSave: async (values: Record<string, Object>): Promise<void> => {
          await this.saveGc(values);
        },
        onClose: (): void => {
          this.closeGcSheet();
        }
      })
    }
    .width('100%')
    .height('100%')
  }
}
