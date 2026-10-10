/*
 * 工作台模块 · 扩展 —— 对齐 PR #7378 features/workbench/ExtensionsSettings.tsx。
 *   GET    /api/plugins                → [{id,name,version,description,enabled,...}]
 *   GET    /api/pawapps                → {apps:[{id,name,version,description,...}]}
 *   POST   /api/plugins/install        → {source:<ZIP URL>, force:false}
 *   DELETE /api/plugins/{id}           → 卸载
 * 两组取数任一 404 → 该组显示「当前 QwenPaw 不支持」；两组都 404 才整页报不支持。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

const PATH_PLUGINS: string = '/plugins';
const PATH_PAWAPPS: string = '/pawapps';

const MODE_NONE: string = '';
const MODE_ACTIONS: string = 'actions';
const MODE_INSTALL: string = 'install';

class PluginRow {
  id: string = '';
  name: string = '';
  version: string = '';
  description: string = '';
  isApp: boolean = false;
}

@Component
export struct ModuleExtensions {
  @State plugins: PluginRow[] = [];
  @State apps: PluginRow[] = [];
  @State pluginsOk: boolean = false;
  @State appsOk: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private target: PluginRow = new PluginRow();
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
      const p: http.HttpResponse = await this.send(PATH_PLUGINS, http.RequestMethod.GET, null);
      this.pluginsOk = p.responseCode >= 200 && p.responseCode < 300;
      this.plugins = this.pluginsOk ? this.parseList(p, false) : [];

      const a: http.HttpResponse = await this.send(PATH_PAWAPPS, http.RequestMethod.GET, null);
      this.appsOk = a.responseCode >= 200 && a.responseCode < 300;
      this.apps = this.appsOk ? this.parseApps(a) : [];

      if (!this.pluginsOk && !this.appsOk) {
        this.error = this.t($r('app.string.module_ext_unsupported'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private rowOf(r: Record<string, Object>, isApp: boolean): PluginRow {
    const row: PluginRow = new PluginRow();
    row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
    row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
    row.version = typeof r['version'] === 'string' ? r['version'] as string : '';
    row.description = typeof r['description'] === 'string' ? r['description'] as string : '';
    row.isApp = isApp;
    return row;
  }

  private parseList(resp: http.HttpResponse, isApp: boolean): PluginRow[] {
    const out: PluginRow[] = [];
    for (const item of jsonArrayOf(resp)) {
      const row: PluginRow = this.rowOf(item as Record<string, Object>, isApp);
      if (row.id.length > 0) {
        out.push(row);
      }
    }
    return out;
  }

  private parseApps(resp: http.HttpResponse): PluginRow[] {
    const out: PluginRow[] = [];
    const apps: Object = jsonOf(resp)['apps'];
    if (apps === undefined || apps === null || !Array.isArray(apps)) {
      return out;
    }
    for (const item of apps as Object[]) {
      const row: PluginRow = this.rowOf(item as Record<string, Object>, true);
      if (row.id.length > 0) {
        out.push(row);
      }
    }
    return out;
  }

  private openActions(row: PluginRow): void {
    this.target = row;
    this.sheetMode = MODE_ACTIONS;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private openInstall(): void {
    this.sheetMode = MODE_INSTALL;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private actions(): SheetOption[] {
    return [optionOf('uninstall', this.t($r('app.string.module_ext_uninstall')))];
  }

  private async onAction(value: string): Promise<void> {
    if (value !== 'uninstall') {
      return;
    }
    const id: string = this.target.id;
    if (this.busy || id.length === 0) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(`/plugins/${encodeURIComponent(id)}`,
        http.RequestMethod.DELETE, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      this.toast(this.t($r('app.string.module_ext_uninstalled')));
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_ext_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private installDefs(): FieldDef[] {
    return [fieldDef('source', this.t($r('app.string.module_ext_source')), 'text', true, '',
      this.t($r('app.string.module_ext_source_help')))];
  }

  // 安装：载荷对齐 7378 —— {source:<ZIP URL>, force:false}
  private async install(values: Record<string, Object>): Promise<void> {
    const raw: Object = values['source'];
    const source: string = typeof raw === 'string' ? (raw as string).trim() : '';
    if (source.length === 0) {
      return;
    }
    const body: Record<string, Object> = {};
    body['source'] = source;
    body['force'] = false;
    const resp: http.HttpResponse = await this.send('/plugins/install', http.RequestMethod.POST,
      JSON.stringify(body));
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    this.toast(this.t($r('app.string.module_ext_installed')));
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
      } else {
        IosGroup({ title: `${this.t($r('app.string.module_ext_group_plugins'))} · ${this.plugins.length}` }) {
          IosRow({
            icon: $r('sys.symbol.arrow_down_to_line'),
            label: this.t($r('app.string.module_ext_install')),
            subtitle: this.t($r('app.string.module_ext_install_hint')),
            tappable: this.pluginsOk && !this.busy,
            onPress: (): void => {
              this.openInstall();
            }
          })
          ForEach(this.plugins, (row: PluginRow) => {
            IosRow({
              icon: $r('sys.symbol.puzzle'),
              label: row.name,
              subtitle: row.version.length > 0 ? row.version : row.description,
              tappable: !this.busy,
              onPress: (): void => {
                this.openActions(row);
              }
            })
          }, (row: PluginRow) => row.id)
        }
        IosGroup({ title: `${this.t($r('app.string.module_ext_group_apps'))} · ${this.apps.length}` }) {
          ForEach(this.apps, (row: PluginRow) => {
            IosRow({
              icon: $r('sys.symbol.square_grid_2x2'),
              label: row.name,
              subtitle: row.version.length > 0 ? row.version : row.description
            })
          }, (row: PluginRow) => row.id)
        }
        if (this.pluginsOk && this.plugins.length === 0 && this.apps.length === 0) {
          ModuleEmpty($r('sys.symbol.puzzle'),
            this.t($r('app.string.module_ext_empty_title')),
            this.t($r('app.string.module_ext_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_ext_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_INSTALL ? 520 : 360, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_INSTALL) {
        FieldSheet({
          title: this.t($r('app.string.module_ext_install')),
          defs: this.installDefs(),
          initial: {} as Record<string, Object>,
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.install(values);
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
