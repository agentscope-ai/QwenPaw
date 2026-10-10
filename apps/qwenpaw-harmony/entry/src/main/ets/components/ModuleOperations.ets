/*
 * 工作台模块 · 备份与运行统计 —— 对齐 PR #7378 features/workbench/OperationsSettings.tsx。
 *   GET  /api/backups                → [{id,name,description,created_at}]
 *   GET  /api/token-usage            → {total_prompt_tokens,total_completion_tokens,total_cache_read_tokens,...}
 *   GET  /api/agent-stats            → {total_active_sessions,total_messages,total_user_messages,...}
 *   GET  /api/backups/{id}           → 备份详情（取 workspace_stats 的 Agent 列表）
 *   POST /api/backups/{id}/restore   → 恢复（载荷口径与 7378 逐字对齐）
 *   POST /api/backups/delete         → {ids:[id]}
 * 某一路 404 → 该组显示「当前 QwenPaw 不支持」并不可点（对齐 7378 的 unsupported 口径）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

const PATH_BACKUPS: string = '/backups';
const PATH_TOKEN: string = '/token-usage';
const PATH_STATS: string = '/agent-stats';

const MODE_NONE: string = '';
const MODE_ACTIONS: string = 'actions';

class BackupRow {
  id: string = '';
  name: string = '';
  description: string = '';
  createdAt: string = '';
}

@Component
export struct ModuleOperations {
  @State backups: BackupRow[] = [];
  @State tokenJson: string = '{}';
  @State statsJson: string = '{}';
  @State backupsOk: boolean = false;
  @State tokenOk: boolean = false;
  @State statsOk: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private target: BackupRow = new BackupRow();
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
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

  private async send(path: string, method: http.RequestMethod,
    body: string | null): Promise<http.HttpResponse> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error('未连接');
    }
    return doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const b: http.HttpResponse = await this.send(PATH_BACKUPS, http.RequestMethod.GET, null);
      this.backupsOk = b.responseCode >= 200 && b.responseCode < 300;
      this.backups = this.backupsOk ? this.parseBackups(b) : [];

      const tk: http.HttpResponse = await this.send(PATH_TOKEN, http.RequestMethod.GET, null);
      this.tokenOk = tk.responseCode >= 200 && tk.responseCode < 300;
      this.tokenJson = this.tokenOk ? JSON.stringify(jsonOf(tk)) : '{}';

      const st: http.HttpResponse = await this.send(PATH_STATS, http.RequestMethod.GET, null);
      this.statsOk = st.responseCode >= 200 && st.responseCode < 300;
      this.statsJson = this.statsOk ? JSON.stringify(jsonOf(st)) : '{}';

      if (!this.backupsOk && !this.tokenOk && !this.statsOk) {
        this.error = this.t($r('app.string.module_ops_unsupported'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private parseBackups(resp: http.HttpResponse): BackupRow[] {
    const out: BackupRow[] = [];
    for (const item of jsonArrayOf(resp)) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: BackupRow = new BackupRow();
      row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
      if (row.id.length === 0) {
        continue;
      }
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
      row.description = typeof r['description'] === 'string' ? r['description'] as string : '';
      row.createdAt = typeof r['created_at'] === 'string' ? r['created_at'] as string : '';
      out.push(row);
    }
    return out;
  }

  private recOf(json: string): Record<string, Object> {
    try {
      return JSON.parse(json) as Record<string, Object>;
    } catch (e) {
      return {} as Record<string, Object>;
    }
  }

  // 千分位（数字本身来自接口，可能极大，不经过本地化 API 避免区域差异）
  private fmtNum(value: Object): string {
    if (typeof value !== 'number') {
      return '—';
    }
    const raw: string = Math.trunc(value as number).toString();
    let out: string = '';
    let count: number = 0;
    for (let i = raw.length - 1; i >= 0; i--) {
      out = raw[i] + out;
      count++;
      if (count % 3 === 0 && i > 0) {
        out = ',' + out;
      }
    }
    return out;
  }

  private stat(json: string, key: string): string {
    return this.fmtNum(this.recOf(json)[key]);
  }

  private openActions(row: BackupRow): void {
    this.target = row;
    this.sheetMode = MODE_ACTIONS;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private actions(): SheetOption[] {
    return [
      optionOf('restore', this.t($r('app.string.module_ops_restore'))),
      optionOf('delete', this.t($r('app.string.module_ops_delete')))
    ];
  }

  private async onAction(value: string): Promise<void> {
    if (value === 'restore') {
      await this.restore();
      return;
    }
    await this.remove();
  }

  // 恢复：先取详情拿 Agent 列表，再按 7378 的载荷整表提交
  private async restore(): Promise<void> {
    const id: string = this.target.id;
    if (this.busy || id.length === 0) {
      return;
    }
    this.busy = true;
    try {
      const det: http.HttpResponse = await this.send(`/backups/${encodeURIComponent(id)}`,
        http.RequestMethod.GET, null);
      const agents: string[] = [];
      if (det.responseCode >= 200 && det.responseCode < 300) {
        const ws: Object = jsonOf(det)['workspace_stats'];
        if (ws !== undefined && ws !== null) {
          for (const key of Object.keys(ws as Record<string, Object>)) {
            agents.push(key);
          }
        }
      }
      const body: Record<string, Object> = {};
      body['include_agents'] = true;
      body['agent_ids'] = agents;
      body['include_global_config'] = true;
      body['include_secrets'] = true;
      body['include_skill_pool'] = true;
      body['mode'] = 'full';
      body['preserve_local_protected_config'] = true;
      const resp: http.HttpResponse = await this.send(
        `/backups/${encodeURIComponent(id)}/restore`, http.RequestMethod.POST,
        JSON.stringify(body));
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      this.toast(this.t($r('app.string.module_ops_restored')));
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_ops_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async remove(): Promise<void> {
    const id: string = this.target.id;
    if (this.busy || id.length === 0) {
      return;
    }
    this.busy = true;
    try {
      const body: Record<string, Object> = {};
      const ids: string[] = [id];
      body['ids'] = ids;
      const resp: http.HttpResponse = await this.send('/backups/delete',
        http.RequestMethod.POST, JSON.stringify(body));
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      this.toast(this.t($r('app.string.module_ops_deleted')));
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_ops_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
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
        IosGroup({ title: this.t($r('app.string.module_ops_group_token')) }) {
          IosRow({
            icon: $r('sys.symbol.arrow_up_to_line'),
            label: this.t($r('app.string.module_ops_prompt')),
            trailing: this.tokenOk ? this.stat(this.tokenJson, 'total_prompt_tokens')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
          IosRow({
            icon: $r('sys.symbol.arrow_down_to_line'),
            label: this.t($r('app.string.module_ops_completion')),
            trailing: this.tokenOk ? this.stat(this.tokenJson, 'total_completion_tokens')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
          IosRow({
            icon: $r('sys.symbol.arrow_clockwise'),
            label: this.t($r('app.string.module_ops_cache')),
            trailing: this.tokenOk ? this.stat(this.tokenJson, 'total_cache_read_tokens')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
        }
        IosGroup({ title: this.t($r('app.string.module_ops_group_stats')) }) {
          IosRow({
            icon: $r('sys.symbol.person_2'),
            label: this.t($r('app.string.module_ops_active_sessions')),
            trailing: this.statsOk ? this.stat(this.statsJson, 'total_active_sessions')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
          IosRow({
            icon: $r('sys.symbol.line_message'),
            label: this.t($r('app.string.module_ops_messages')),
            trailing: this.statsOk ? this.stat(this.statsJson, 'total_messages')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
          IosRow({
            icon: $r('sys.symbol.person'),
            label: this.t($r('app.string.module_ops_user_messages')),
            trailing: this.statsOk ? this.stat(this.statsJson, 'total_user_messages')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
          IosRow({
            icon: $r('sys.symbol.wand_and_stars'),
            label: this.t($r('app.string.module_ops_assistant_messages')),
            trailing: this.statsOk ? this.stat(this.statsJson, 'total_assistant_messages')
              : this.t($r('app.string.module_ops_unsupported_short'))
          })
        }
        IosGroup({ title: `${this.t($r('app.string.module_ops_group_backups'))} · ${this.backups.length}` }) {
          ForEach(this.backups, (row: BackupRow) => {
            IosRow({
              icon: $r('sys.symbol.doc_text'),
              label: row.name,
              subtitle: row.description.length > 0 ? row.description : row.createdAt,
              tappable: this.backupsOk && !this.busy,
              onPress: (): void => {
                this.openActions(row);
              }
            })
          }, (row: BackupRow) => row.id)
        }
        if (this.backupsOk && this.backups.length === 0) {
          ModuleEmpty($r('sys.symbol.doc_text'),
            this.t($r('app.string.module_ops_empty_title')),
            this.t($r('app.string.module_ops_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_ops_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(360, this.gate, (v: boolean): void => {
        this.sheetShown = v;
      }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_ACTIONS) {
        OptionsSheet({
          title: this.target.name,
          options: this.actions(),
          current: '',
          onPick: (v: string): void => {
            this.onAction(v);
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
}
