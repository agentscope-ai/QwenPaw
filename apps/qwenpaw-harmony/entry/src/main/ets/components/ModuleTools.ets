/*
 * 工作台模块 · Tools —— 对齐 PR #7378 features/workbench/ToggleCollectionSettings.tsx（kind = tools）。
 *   GET   /api/tools                            → [{name, description, enabled, config_fields, config_values, ...}]
 *   PATCH /api/tools/{name}/toggle               开关（乐观更新，失败提示）
 *   PATCH /api/tools/{name}/async-execution      {async_execution}
 *   POST  /api/tools/{name}/config               {config}
 * 行副标题取 description；点行打开配置表单（工具自带 config_fields + 「后台异步执行」开关）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { UiTokens } from '../theme/UiTokens';

const ASYNC_KEY: string = '__async_execution';

class ToolItem {
  name: string = '';
  description: string = '';
  enabled: boolean = false;
  asyncExecution: boolean = false;
  configFields: string = '[]';       // 原样透传的 config_fields JSON
  configValues: string = '{}';
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

// config_fields（[{name,label,type,required,placeholder,help,options,default}]）→ FieldDef[]
function defsOf(raw: string, t: (res: Resource) => string): FieldDef[] {
  const out: FieldDef[] = [];
  try {
    const parsed: Object = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      for (const item of parsed as Object[]) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const name: string = strOf(r['name'], '');
        if (name.length === 0) {
          continue;
        }
        const type: string = strOf(r['type'], 'text');
        if (type !== 'text' && type !== 'password' && type !== 'number' && type !== 'boolean'
          && type !== 'select' && type !== 'textarea' && type !== 'switch') {
          continue;
        }
        const options: string[] = [];
        const opt: Object = r['options'];
        if (Array.isArray(opt)) {
          for (const o of opt as Object[]) {
            if (typeof o === 'string') {
              options.push(o as string);
            }
          }
        }
        out.push(fieldDef(name, strOf(r['label'], name), type, r['required'] === true,
          strOf(r['placeholder'], ''), strOf(r['help'], ''), options));
      }
    }
  } catch (e) {
    // config_fields 非法 JSON：退化为只有异步开关
  }
  out.push(fieldDef(ASYNC_KEY, t($r('app.string.module_tools_async')), 'boolean', false, '',
    t($r('app.string.module_tools_async_help'))));
  return out;
}

function initialOf(tool: ToolItem): Record<string, Object> {
  const out: Record<string, Object> = {};
  try {
    const parsed: Object = JSON.parse(tool.configValues);
    const r: Record<string, Object> = parsed as Record<string, Object>;
    for (const key of Object.keys(r)) {
      out[key] = r[key];
    }
  } catch (e) {
    // 非 JSON：忽略，交由表单默认值
  }
  out[ASYNC_KEY] = tool.asyncExecution;
  return out;
}

@Component
export struct ModuleTools {
  @State items: ToolItem[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  private editing: ToolItem = new ToolItem();
  private editingDefs: FieldDef[] = [];
  private editingInitial: Record<string, Object> = {};
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
      const resp: http.HttpResponse = await this.send('/tools', http.RequestMethod.GET, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const out: ToolItem[] = [];
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const tool: ToolItem = new ToolItem();
        tool.name = strOf(r['name'], '');
        if (tool.name.length === 0) {
          continue;
        }
        tool.description = strOf(r['description'], '');
        tool.enabled = r['enabled'] === true;
        tool.asyncExecution = r['async_execution'] === true;
        tool.configFields = JSON.stringify(r['config_fields'] !== undefined && r['config_fields'] !== null
          ? r['config_fields'] : []);
        tool.configValues = JSON.stringify(r['config_values'] !== undefined && r['config_values'] !== null
          ? r['config_values'] : {});
        out.push(tool);
      }
      this.items = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private enabledCount(): number {
    let n: number = 0;
    for (const item of this.items) {
      if (item.enabled) {
        n++;
      }
    }
    return n;
  }

  private async toggle(item: ToolItem): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(
        `/tools/${encodeURIComponent(item.name)}/toggle`, http.RequestMethod.PATCH, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const next: ToolItem[] = [];
      for (const it of this.items) {
        const copy: ToolItem = new ToolItem();
        copy.name = it.name;
        copy.description = it.description;
        copy.asyncExecution = it.asyncExecution;
        copy.configFields = it.configFields;
        copy.configValues = it.configValues;
        copy.enabled = it.name === item.name ? !it.enabled : it.enabled;
        next.push(copy);
      }
      this.items = next;
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_tools_save_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private openConfig(item: ToolItem): void {
    this.editing = item;
    this.editingDefs = defsOf(item.configFields, (res: Resource): string => this.t(res));
    this.editingInitial = initialOf(item);
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private async saveConfig(values: Record<string, Object>): Promise<void> {
    const tool: ToolItem = this.editing;
    await this.send(`/tools/${encodeURIComponent(tool.name)}/async-execution`,
      http.RequestMethod.PATCH,
      JSON.stringify({ 'async_execution': values[ASYNC_KEY] === true }));
    const config: Record<string, Object> = {};
    for (const key of Object.keys(values)) {
      if (key !== ASYNC_KEY) {
        config[key] = values[key];
      }
    }
    if (Object.keys(config).length > 0) {
      await this.send(`/tools/${encodeURIComponent(tool.name)}/config`,
        http.RequestMethod.POST, JSON.stringify({ 'config': config }));
    }
    await this.load();
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(this.t($r('app.string.module_loading')))
      } else if (this.items.length === 0) {
        ModuleEmpty($r('sys.symbol.wrench_and_screwdriver'),
          this.t($r('app.string.module_tools_empty_title')),
          this.t($r('app.string.module_tools_empty_subtitle')))
      } else {
        IosGroup({ title: `${this.t($r('app.string.module_tools_group'))} · `
          + `${this.enabledCount()}/${this.items.length} ${this.t($r('app.string.module_tools_enabled'))}` }) {
          ForEach(this.items, (item: ToolItem) => {
            IosRow({
              icon: $r('sys.symbol.wrench_and_screwdriver'),
              label: item.name,
              subtitle: item.description,
              hasSwitch: true,
              switchOn: item.enabled,
              tappable: true,
              onSwitch: (): void => {
                this.toggle(item);
              },
              onPress: (): void => {
                this.openConfig(item);
              }
            })
          }, (item: ToolItem) => item.name)
        }
        ModuleFooter(this.t($r('app.string.module_tools_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.configSheet(),
      moduleSheetOptions(620, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  configSheet() {
    Column() {
      FieldSheet({
        title: this.editing.name,
        defs: this.editingDefs,
        initial: this.editingInitial,
        onSave: async (values: Record<string, Object>): Promise<void> => {
          await this.saveConfig(values);
        },
        onClose: (): void => {
          this.closeSheet();
        }
      })
    }
    .width('100%')
    .height('100%')
  }
}
