/*
 * 工作台模块 · MCP —— 对齐 PR #7378 features/workbench/McpSettings.tsx。
 *   GET    /api/mcp                     → [{key, name, description, enabled, transport, url, headers,
 *                                          command, args, access_summary{default_effect}, oauth_status{authorized}}]
 *   PATCH  /api/mcp/toggle/{key}         开关
 *   POST   /api/mcp                      {client_key, client} 新增 / 编辑
 *   DELETE /api/mcp/{key}                删除（行操作菜单，二次确认）
 * 行副标题 = transport · 默认访问效果 · OAuth 已授权；点行开操作菜单（编辑 / 删除）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

class McpClientInfo {
  key: string = '';
  name: string = '';
  description: string = '';
  enabled: boolean = false;
  transport: string = '';
  url: string = '';
  command: string = '';
  args: string = '';        // 逗号分隔展示
  defaultEffect: string = '';
  oauthAuthorized: boolean = false;
}

const MODE_NONE: string = '';
const MODE_FORM: string = 'form';
const MODE_ACTIONS: string = 'actions';

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

@Component
export struct ModuleMcpAcp {
  @State clients: McpClientInfo[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private target: McpClientInfo = new McpClientInfo();
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
      const resp: http.HttpResponse = await this.send('/mcp', http.RequestMethod.GET, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const out: McpClientInfo[] = [];
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const info: McpClientInfo = new McpClientInfo();
        info.key = strOf(r['key'], '');
        if (info.key.length === 0) {
          continue;
        }
        info.name = strOf(r['name'], info.key);
        info.description = strOf(r['description'], '');
        info.enabled = r['enabled'] === true;
        info.transport = strOf(r['transport'], '');
        info.url = strOf(r['url'], '');
        info.command = strOf(r['command'], '');
        const args: string[] = [];
        const rawArgs: Object = r['args'];
        if (Array.isArray(rawArgs)) {
          for (const a of rawArgs as Object[]) {
            if (typeof a === 'string') {
              args.push(a as string);
            }
          }
        }
        info.args = args.join(', ');
        const access: Object = r['access_summary'];
        if (access !== undefined && access !== null) {
          info.defaultEffect = strOf((access as Record<string, Object>)['default_effect'], '');
        }
        const oauth: Object = r['oauth_status'];
        if (oauth !== undefined && oauth !== null) {
          info.oauthAuthorized = (oauth as Record<string, Object>)['authorized'] === true;
        }
        out.push(info);
      }
      this.clients = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private subtitleOf(info: McpClientInfo): string {
    let s: string = info.transport;
    if (info.defaultEffect.length > 0) {
      s += ` · ${info.defaultEffect}`;
    }
    if (info.oauthAuthorized) {
      s += ` · ${this.t($r('app.string.module_mcp_oauth_ok'))}`;
    }
    return s;
  }

  private async toggle(info: McpClientInfo): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(
        `/mcp/toggle/${encodeURIComponent(info.key)}`, http.RequestMethod.PATCH, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_mcp_save_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private openForm(info: McpClientInfo | null): void {
    this.target = info !== null ? info : new McpClientInfo();
    if (info === null) {
      this.target.transport = 'stdio';
    }
    this.sheetMode = MODE_FORM;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private openActions(info: McpClientInfo): void {
    this.target = info;
    this.sheetMode = MODE_ACTIONS;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private defs(): FieldDef[] {
    return [
      fieldDef('name', this.t($r('app.string.module_mcp_field_name')), 'text', true),
      fieldDef('transport', this.t($r('app.string.module_mcp_field_transport')), 'select', true, '',
        '', ['stdio', 'streamable_http', 'sse']),
      fieldDef('url', this.t($r('app.string.module_mcp_field_url')), 'text', false, '',
        this.t($r('app.string.module_mcp_field_url_help'))),
      fieldDef('command', this.t($r('app.string.module_mcp_field_command')), 'text', false, '',
        this.t($r('app.string.module_mcp_field_command_help'))),
      fieldDef('args', this.t($r('app.string.module_mcp_field_args')), 'text', false, '',
        this.t($r('app.string.module_mcp_field_args_help'))),
      fieldDef('description', this.t($r('app.string.module_mcp_field_desc')), 'text')
    ];
  }

  private initial(): Record<string, Object> {
    const out: Record<string, Object> = {};
    if (this.sheetMode !== MODE_FORM || this.target.key.length === 0) {
      return out;
    }
    out['name'] = this.target.name;
    out['transport'] = this.target.transport;
    out['url'] = this.target.url;
    out['command'] = this.target.command;
    out['args'] = this.target.args;
    out['description'] = this.target.description;
    return out;
  }

  private async saveForm(values: Record<string, Object>): Promise<void> {
    const name: string = strOf(values['name'], '').trim();
    const transport: string = strOf(values['transport'], 'stdio');
    const client: Record<string, Object> = {};
    client['name'] = name;
    client['description'] = strOf(values['description'], '');
    client['transport'] = transport;
    client['enabled'] = this.target.key.length > 0 ? this.target.enabled : true;
    const url: string = strOf(values['url'], '').trim();
    if (url.length > 0) {
      client['url'] = url;
    }
    const command: string = strOf(values['command'], '').trim();
    if (command.length > 0) {
      client['command'] = command;
    }
    const args: string[] = [];
    for (const raw of strOf(values['args'], '').split(',')) {
      const a: string = raw.trim();
      if (a.length > 0) {
        args.push(a);
      }
    }
    if (args.length > 0) {
      client['args'] = args;
    }
    const body: Record<string, Object> = {};
    body['client_key'] = this.target.key.length > 0 ? this.target.key : name;
    body['client'] = client;
    const resp: http.HttpResponse = await this.send('/mcp', http.RequestMethod.POST,
      JSON.stringify(body));
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    await this.load();
  }

  private async remove(): Promise<void> {
    const key: string = this.target.key;
    if (this.busy || key.length === 0) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(`/mcp/${encodeURIComponent(key)}`,
        http.RequestMethod.DELETE, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_mcp_delete_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private actions(): SheetOption[] {
    return [
      optionOf('edit', this.t($r('app.string.module_edit'))),
      optionOf('delete', this.t($r('app.string.module_mcp_delete')))
    ];
  }

  private async onAction(value: string): Promise<void> {
    if (value === 'edit') {
      this.closeSheet();
      this.openForm(this.target);
      return;
    }
    await this.remove();
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
        IosGroup({ title: `${this.t($r('app.string.module_mcp_group'))} · ${this.clients.length}` }) {
          IosRow({
            icon: $r('sys.symbol.puzzle'),
            label: this.t($r('app.string.module_mcp_add')),
            subtitle: this.t($r('app.string.module_mcp_add_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.openForm(null);
            }
          })
          ForEach(this.clients, (info: McpClientInfo) => {
            IosRow({
              icon: $r('sys.symbol.puzzle'),
              label: info.name,
              subtitle: this.subtitleOf(info),
              hasSwitch: true,
              switchOn: info.enabled,
              tappable: true,
              onSwitch: (): void => {
                this.toggle(info);
              },
              onPress: (): void => {
                this.openActions(info);
              }
            })
          }, (info: McpClientInfo) => info.key)
        }
        if (this.clients.length === 0) {
          ModuleEmpty($r('sys.symbol.puzzle'),
            this.t($r('app.string.module_mcp_empty_title')),
            this.t($r('app.string.module_mcp_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_mcp_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_FORM ? 700 : 360, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_FORM) {
        FieldSheet({
          title: this.target.key.length > 0
            ? `${this.t($r('app.string.module_edit'))} ${this.target.name}`
            : this.t($r('app.string.module_mcp_add')),
          defs: this.defs(),
          initial: this.initial(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveForm(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.sheetMode === MODE_ACTIONS) {
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
