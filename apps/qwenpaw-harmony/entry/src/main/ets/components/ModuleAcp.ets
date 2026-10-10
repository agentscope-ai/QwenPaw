/*
 * 工作台模块 · ACP —— 对齐 PR #7378 features/workbench/AcpSettings.tsx。
 *   GET  /api/config/acp                → { node_path?, agents: { 名字: {...} } }
 *   PUT  /api/config/acp                → 整表保存（新增 / 改名 / 删除都走整表：后端无 DELETE 路由）
 *   GET  /api/config/acp/node-runtime   → { node_path, effective_node_path, candidates[] }
 *   PUT  /api/config/acp/node-runtime   → { node_path }
 *   PUT  /api/config/acp/{名字}          → 单 Agent（开关启用态）
 * Agent 字段与取值规则逐条对齐 7378：
 *   enabled / command / args / env / trusted / tool_parse_mode / stdio_buffer_limit_bytes。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';

const DEFAULT_BUFFER: number = 52428800;

class AcpAgent {
  name: string = '';
  enabled: boolean = true;
  command: string = '';
  args: string[] = [];
  env: Record<string, string> = {};
  trusted: boolean = false;
  toolParseMode: string = 'call_title';
  bufferLimit: number = DEFAULT_BUFFER;
}

@Component
export struct ModuleAcp {
  @State agents: AcpAgent[] = [];
  @State nodePath: string = '';
  @State effectiveNodePath: string = '';
  @State availableRuntimes: number = 0;
  @State loaded: boolean = false;
  @State error: string = '';
  // '' = 未打开；'new' = 新增；'runtime' = Node 运行时；其余 = 正在编辑的 Agent 名
  @State editing: string = '';
  @State sheetShown: boolean = false;
  // 半模态单向绑定（不用 $$）：框架回退动画结束时会回写 isShow，会把随后打开的新面板关掉
  private gate: SheetGate = new SheetGate();

  // 打开 / 关闭半模态唯一入口：目标字段已先置好，闸门只决定打开时机（回退动画期间排队）
  private openSheet(): void {
    if (!this.gate.request()) {
      return;
    }
    this.sheetShown = true;
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private busy: boolean = false;

  aboutToAppear(): void {
    this.load();
  }

  private async conn(): Promise<QpConnection | null> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadConnection(ctx);
  }

  private async load(): Promise<void> {
    const c: QpConnection | null = await this.conn();
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    try {
      const cfgResp: http.HttpResponse = await doRequest(`${c.baseUrl}/api/config/acp`,
        http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
      const rtResp: http.HttpResponse = await doRequest(`${c.baseUrl}/api/config/acp/node-runtime`,
        http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
      if (cfgResp.responseCode !== 200 || rtResp.responseCode !== 200) {
        this.error = `HTTP ${cfgResp.responseCode} / ${rtResp.responseCode}`;
        this.loaded = true;
        return;
      }
      this.applyConfig(jsonOf(cfgResp));
      this.applyRuntime(jsonOf(rtResp));
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private applyConfig(data: Record<string, Object>): void {
    const np: Object = data['node_path'];
    this.nodePath = typeof np === 'string' ? np as string : '';
    const list: AcpAgent[] = [];
    const raw: Object = data['agents'];
    if (raw !== null && raw !== undefined && typeof raw === 'object' && !Array.isArray(raw)) {
      const rec: Record<string, Object> = raw as Record<string, Object>;
      for (const name of Object.keys(rec)) {
        const v: Object = rec[name];
        if (v === null || v === undefined || typeof v !== 'object') {
          continue;
        }
        list.push(this.parseAgent(name, v as Record<string, Object>));
      }
    }
    list.sort((a: AcpAgent, b: AcpAgent): number => a.name < b.name ? -1 : (a.name > b.name ? 1 : 0));
    this.agents = list;
  }

  private parseAgent(name: string, rec: Record<string, Object>): AcpAgent {
    const a: AcpAgent = new AcpAgent();
    a.name = name;
    a.enabled = rec['enabled'] === true;
    const cmd: Object = rec['command'];
    a.command = typeof cmd === 'string' ? cmd as string : '';
    const args: Object = rec['args'];
    if (Array.isArray(args)) {
      const out: string[] = [];
      for (const item of args as Object[]) {
        out.push(`${item}`);
      }
      a.args = out;
    }
    const env: Object = rec['env'];
    if (env !== null && env !== undefined && typeof env === 'object' && !Array.isArray(env)) {
      const er: Record<string, Object> = env as Record<string, Object>;
      const map: Record<string, string> = {};
      for (const k of Object.keys(er)) {
        map[k] = `${er[k]}`;
      }
      a.env = map;
    }
    a.trusted = rec['trusted'] === true;
    const mode: Object = rec['tool_parse_mode'];
    a.toolParseMode = typeof mode === 'string' ? mode as string : 'call_title';
    const limit: Object = rec['stdio_buffer_limit_bytes'];
    a.bufferLimit = typeof limit === 'number' ? limit as number : DEFAULT_BUFFER;
    return a;
  }

  private applyRuntime(data: Record<string, Object>): void {
    const np: Object = data['node_path'];
    this.nodePath = typeof np === 'string' ? np as string : '';
    const eff: Object = data['effective_node_path'];
    this.effectiveNodePath = typeof eff === 'string' ? eff as string : '';
    let available: number = 0;
    const cands: Object = data['candidates'];
    if (Array.isArray(cands)) {
      for (const item of cands as Object[]) {
        const rec: Record<string, Object> = item as Record<string, Object>;
        if (rec['available'] === true) {
          available = available + 1;
        }
      }
    }
    this.availableRuntimes = available;
  }

  // —— 保存 ——

  private async put(path: string, body: string): Promise<Record<string, Object>> {
    const c: QpConnection | null = await this.conn();
    if (c === null) {
      throw new Error(this.t($r('app.string.module_not_connected')));
    }
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}${path}`,
      http.RequestMethod.PUT, body, c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    return jsonOf(resp);
  }

  private configJson(override: AcpAgent[] | null): Record<string, Object> {
    const agents: Record<string, Object> = {};
    const list: AcpAgent[] = override !== null ? override : this.agents;
    for (const a of list) {
      const rec: Record<string, Object> = {};
      rec['enabled'] = a.enabled;
      rec['command'] = a.command;
      rec['args'] = a.args;
      rec['env'] = a.env;
      rec['trusted'] = a.trusted;
      rec['tool_parse_mode'] = a.toolParseMode;
      rec['stdio_buffer_limit_bytes'] = a.bufferLimit;
      agents[a.name] = rec;
    }
    const out: Record<string, Object> = {};
    if (this.nodePath.length > 0) {
      out['node_path'] = this.nodePath;
    }
    out['agents'] = agents;
    return out;
  }

  private agentJson(a: AcpAgent): string {
    const rec: Record<string, Object> = {};
    rec['enabled'] = a.enabled;
    rec['command'] = a.command;
    rec['args'] = a.args;
    rec['env'] = a.env;
    rec['trusted'] = a.trusted;
    rec['tool_parse_mode'] = a.toolParseMode;
    rec['stdio_buffer_limit_bytes'] = a.bufferLimit;
    return JSON.stringify(rec);
  }

  private async saveWhole(list: AcpAgent[] | null): Promise<void> {
    this.applyConfig(await this.put('/api/config/acp', JSON.stringify(this.configJson(list))));
  }

  private async toggle(a: AcpAgent): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    const next: AcpAgent = new AcpAgent();
    next.name = a.name;
    next.enabled = !a.enabled;
    next.command = a.command;
    next.args = a.args;
    next.env = a.env;
    next.trusted = a.trusted;
    next.toolParseMode = a.toolParseMode;
    next.bufferLimit = a.bufferLimit;
    try {
      await this.put(`/api/config/acp/${encodeURIComponent(a.name)}`, this.agentJson(next));
      await this.load();
    } catch (e) {
      this.toast(this.t($r('app.string.module_acp_save_failed')));
    } finally {
      this.busy = false;
    }
  }

  private async saveRuntime(values: Record<string, Object>): Promise<void> {
    const v: Object = values['node_path'];
    const body: Record<string, string> = { 'node_path': typeof v === 'string' ? v as string : '' };
    this.applyRuntime(await this.put('/api/config/acp/node-runtime', JSON.stringify(body)));
  }

  private async saveAgent(values: Record<string, Object>): Promise<void> {
    const nameRaw: Object = values['name'];
    const name: string = (typeof nameRaw === 'string' ? nameRaw as string : '').trim();
    if (name.length === 0) {
      throw new Error(this.t($r('app.string.module_acp_agent_id')));
    }
    const cmdRaw: Object = values['command'];
    const command: string = (typeof cmdRaw === 'string' ? cmdRaw as string : '').trim();
    if (command.length === 0) {
      throw new Error(this.t($r('app.string.module_acp_command_required')));
    }
    const argsRaw: Object = values['args'];
    const argsText: string = typeof argsRaw === 'string' ? argsRaw as string : '';
    const args: string[] = [];
    for (const line of argsText.split('\n')) {
      const t: string = line.trim();
      if (t.length > 0) {
        args.push(t);
      }
    }
    const envRaw: Object = values['env'];
    const env: Record<string, string> = this.parseEnv(typeof envRaw === 'string' ? envRaw as string : '');
    const limitRaw: Object = values['stdio_buffer_limit_bytes'];
    const limit: number = typeof limitRaw === 'number' && (limitRaw as number) > 0
      ? limitRaw as number : DEFAULT_BUFFER;
    const current: AcpAgent | null = this.agentOf(this.editing);
    const agent: AcpAgent = new AcpAgent();
    agent.name = name;
    agent.enabled = current !== null ? current.enabled : true;
    agent.command = command;
    agent.args = args;
    agent.env = env;
    agent.trusted = values['trusted'] === true;
    const modeRaw: Object = values['tool_parse_mode'];
    agent.toolParseMode = typeof modeRaw === 'string' && (modeRaw as string).length > 0
      ? modeRaw as string : 'call_title';
    agent.bufferLimit = limit;
    // 改名 = 先删旧键再加新键（后端无单独改名路由，整表提交）
    const next: AcpAgent[] = [];
    for (const a of this.agents) {
      if (a.name !== this.editing && a.name !== name) {
        next.push(a);
      }
    }
    next.push(agent);
    await this.saveWhole(next);
  }

  private parseEnv(text: string): Record<string, string> {
    const trimmed: string = text.trim();
    if (trimmed.length === 0) {
      return {};
    }
    let parsed: Object;
    try {
      parsed = JSON.parse(trimmed) as Object;
    } catch (e) {
      throw new Error(this.t($r('app.string.module_acp_env_invalid')));
    }
    if (parsed === null || parsed === undefined || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(this.t($r('app.string.module_acp_env_invalid')));
    }
    const rec: Record<string, Object> = parsed as Record<string, Object>;
    const out: Record<string, string> = {};
    for (const k of Object.keys(rec)) {
      out[k] = `${rec[k]}`;
    }
    return out;
  }

  private agentOf(name: string): AcpAgent | null {
    for (const a of this.agents) {
      if (a.name === name) {
        return a;
      }
    }
    return null;
  }

  private remove(name: string): void {
    const next: AcpAgent[] = [];
    for (const a of this.agents) {
      if (a.name !== name) {
        next.push(a);
      }
    }
    this.saveWhole(next).catch((reason: Object): void => {
      this.toast(this.t($r('app.string.module_acp_delete_failed')));
    });
  }

  private openActions(name: string): void {
    this.getUIContext().showActionSheet({
      title: name,
      message: $r('app.string.module_acp_agent_title'),
      sheets: [
        {
          title: $r('app.string.module_edit'),
          action: (): void => {
            this.editing = name;
            this.openSheet();
          }
        },
        {
          title: $r('app.string.module_delete'),
          action: (): void => {
            this.remove(name);
          }
        }
      ]
    });
  }

  private agentDefs(): FieldDef[] {
    const name: FieldDef = fieldDef('name', this.t($r('app.string.module_acp_agent_id')), 'text', true);
    const command: FieldDef = fieldDef('command', this.t($r('app.string.module_acp_command')), 'text',
      true, 'npx');
    const args: FieldDef = fieldDef('args', this.t($r('app.string.module_acp_args')), 'textarea',
      false, '', this.t($r('app.string.module_acp_args_help')));
    const env: FieldDef = fieldDef('env', this.t($r('app.string.module_acp_env')), 'textarea',
      false, '', this.t($r('app.string.module_acp_env_help')));
    const trusted: FieldDef = fieldDef('trusted', this.t($r('app.string.module_acp_trust')), 'boolean');
    const mode: FieldDef = fieldDef('tool_parse_mode', this.t($r('app.string.module_acp_parse')), 'select',
      false, '', '', ['call_title', 'update_detail', 'call_detail']);
    mode.defText = 'call_title';
    const limit: FieldDef = fieldDef('stdio_buffer_limit_bytes',
      this.t($r('app.string.module_acp_buffer')), 'number');
    return [name, command, args, env, trusted, mode, limit];
  }

  private agentInitial(): Record<string, Object> {
    const out: Record<string, Object> = {};
    const a: AcpAgent | null = this.agentOf(this.editing);
    if (a !== null) {
      out['name'] = a.name;
      out['command'] = a.command;
      out['args'] = a.args.join('\n');
      out['env'] = JSON.stringify(a.env, null, 2);
      out['trusted'] = a.trusted;
      out['tool_parse_mode'] = a.toolParseMode;
      out['stdio_buffer_limit_bytes'] = a.bufferLimit;
    } else {
      out['trusted'] = false;
      out['tool_parse_mode'] = 'call_title';
      out['stdio_buffer_limit_bytes'] = DEFAULT_BUFFER;
    }
    return out;
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.editing === 'runtime') {
        FieldSheet({
          title: this.t($r('app.string.module_acp_node_path')),
          defs: [fieldDef('node_path', this.t($r('app.string.module_acp_node_path')), 'text')],
          initial: { 'node_path': this.nodePath },
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveRuntime(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else {
        FieldSheet({
          title: this.editing === 'new' ? this.t($r('app.string.module_acp_add'))
            : `${this.t($r('app.string.module_edit'))}${this.editing}`,
          defs: this.agentDefs(),
          initial: this.agentInitial(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveAgent(values);
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
        ModuleLoading(this.t($r('app.string.module_loading')))
      } else {
        IosGroup({ title: this.t($r('app.string.module_acp_runtime')) }) {
          IosRow({
            icon: $r('sys.symbol.code_square'),
            label: 'Node.js',
            subtitle: `${this.availableRuntimes} ${this.t($r('app.string.module_acp_runtimes'))}`,
            trailing: this.effectiveNodePath.length > 0 ? this.effectiveNodePath
              : this.t($r('app.string.module_acp_not_detected')),
            tappable: true,
            onPress: (): void => {
              this.editing = 'runtime';
              this.openSheet();
            }
          })
        }
        IosGroup({ title: `ACP Agents · ${this.agents.length}` }) {
          IosRow({
            icon: $r('sys.symbol.plus'),
            label: this.t($r('app.string.module_acp_add')),
            subtitle: this.t($r('app.string.module_acp_add_hint')),
            tappable: true,
            onPress: (): void => {
              this.editing = 'new';
              this.openSheet();
            }
          })
          ForEach(this.agents, (a: AcpAgent) => {
            IosRow({
              icon: $r('sys.symbol.link'),
              label: a.name,
              subtitle: `${a.command} · ${a.trusted
                ? this.t($r('app.string.module_acp_trusted'))
                : this.t($r('app.string.module_acp_need_approval'))}`,
              hasSwitch: true,
              switchOn: a.enabled,
              onSwitch: (): void => {
                this.toggle(a);
              },
              tappable: true,
              onPress: (): void => {
                this.openActions(a.name);
              }
            })
          }, (a: AcpAgent) => a.name)
        }
        if (this.agents.length === 0) {
          ModuleEmpty($r('sys.symbol.link'),
            this.t($r('app.string.module_acp_empty_title')),
            this.t($r('app.string.module_acp_empty_copy')))
        }
        ModuleFooter(this.t($r('app.string.module_acp_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(600, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }
}
