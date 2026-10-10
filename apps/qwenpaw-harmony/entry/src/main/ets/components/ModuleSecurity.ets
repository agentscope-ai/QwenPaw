/*
 * 工作台模块 · Security —— 对齐 PR #7378 features/workbench/SecuritySettings.tsx。
 *   五路配置（GET 取原文档，PUT 整表回写以保留未展示字段）：
 *     GET/PUT /api/config/security/sandbox                 {enabled, effective, reason}
 *     GET/PUT /api/config/security/tool-guard              {enabled, denied_tools[], custom_rules[], ...}
 *     GET/PUT /api/config/security/file-guard              {enabled, paths[], allow_preview_outside_workspace}
 *     GET/PUT /api/config/security/skill-scanner           {mode, timeout, whitelist[]}
 *     GET/PUT /api/config/security/allow-no-auth-hosts     {hosts[]}
 * 某一路 404 → 该行显示「当前 QwenPaw 不支持」并不可点（对齐 7378 的 unsupported 口径）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

const PATH_SANDBOX: string = '/config/security/sandbox';
const PATH_GUARD: string = '/config/security/tool-guard';
const PATH_FILE: string = '/config/security/file-guard';
const PATH_SCANNER: string = '/config/security/skill-scanner';
const PATH_HOSTS: string = '/config/security/allow-no-auth-hosts';

const MODE_NONE: string = '';
const MODE_SCANNER: string = 'scanner';
const MODE_HOSTS: string = 'hosts';

@Component
export struct ModuleSecurity {
  @State sandboxJson: string = '{}';
  @State guardJson: string = '{}';
  @State fileJson: string = '{}';
  @State scannerJson: string = '{}';
  @State hostsJson: string = '{}';
  @State sandboxOk: boolean = false;
  @State guardOk: boolean = false;
  @State fileOk: boolean = false;
  @State scannerOk: boolean = false;
  @State hostsOk: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
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
    body: string | null): Promise<Record<string, Object> | null> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error('未连接');
    }
    const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
    if (resp.responseCode === 404) {
      return null;
    }
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    if (method !== http.RequestMethod.GET) {
      return null;
    }
    return jsonOf(resp);
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
      const sandbox: Record<string, Object> | null = await this.send(PATH_SANDBOX,
        http.RequestMethod.GET, null);
      this.sandboxJson = JSON.stringify(sandbox !== null ? sandbox : {});
      this.sandboxOk = sandbox !== null;
      const guard: Record<string, Object> | null = await this.send(PATH_GUARD,
        http.RequestMethod.GET, null);
      this.guardJson = JSON.stringify(guard !== null ? guard : {});
      this.guardOk = guard !== null;
      const file: Record<string, Object> | null = await this.send(PATH_FILE,
        http.RequestMethod.GET, null);
      this.fileJson = JSON.stringify(file !== null ? file : {});
      this.fileOk = file !== null;
      const scanner: Record<string, Object> | null = await this.send(PATH_SCANNER,
        http.RequestMethod.GET, null);
      this.scannerJson = JSON.stringify(scanner !== null ? scanner : {});
      this.scannerOk = scanner !== null;
      const hosts: Record<string, Object> | null = await this.send(PATH_HOSTS,
        http.RequestMethod.GET, null);
      this.hostsJson = JSON.stringify(hosts !== null ? hosts : {});
      this.hostsOk = hosts !== null;
      if (!this.sandboxOk && !this.guardOk && !this.fileOk && !this.scannerOk && !this.hostsOk) {
        this.error = this.t($r('app.string.module_sec_unsupported_all'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private recOf(json: string): Record<string, Object> {
    try {
      return JSON.parse(json) as Record<string, Object>;
    } catch (e) {
      return {} as Record<string, Object>;
    }
  }

  private enabledOf(json: string): boolean {
    return this.recOf(json)['enabled'] === true;
  }

  private modeOf(json: string): string {
    const v: Object = this.recOf(json)['mode'];
    return typeof v === 'string' ? v as string : 'off';
  }

  private hostsText(): string {
    const raw: Object = this.recOf(this.hostsJson)['hosts'];
    const out: string[] = [];
    if (Array.isArray(raw)) {
      for (const h of raw as Object[]) {
        if (typeof h === 'string') {
          out.push(h as string);
        }
      }
    }
    return out.join(', ');
  }

  private modeLabel(): string {
    const mode: string = this.modeOf(this.scannerJson);
    if (mode === 'block') {
      return this.t($r('app.string.module_sec_scan_block'));
    }
    if (mode === 'warn') {
      return this.t($r('app.string.module_sec_scan_warn'));
    }
    return this.t($r('app.string.module_sec_scan_off'));
  }

  // 整表回写：以 GET 原文档为底，只覆盖目标字段（未展示字段原样带回）
  private async putMerge(path: string, json: string,
    patch: Record<string, Object>, slot: string): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const body: Record<string, Object> = this.recOf(json);
      for (const key of Object.keys(patch)) {
        body[key] = patch[key];
      }
      const resp: http.HttpResponse = await this.sendRaw(path, JSON.stringify(body));
      if (resp.responseCode === 404) {
        this.toast(this.t($r('app.string.module_sec_unsupported')));
        return;
      }
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      // 服务端回写文档则以其为准，否则用本地合并结果
      const result: Object = resp.result;
      if (typeof result === 'string' && (result as string).trim().startsWith('{')) {
        this.applySlot(slot, result as string);
      } else {
        this.applySlot(slot, JSON.stringify(body));
      }
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_sec_save_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async sendRaw(path: string, body: string): Promise<http.HttpResponse> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error('未连接');
    }
    return doRequest(`${c.baseUrl}/api${path}`, http.RequestMethod.PUT, body,
      c.token.length > 0 ? c.token : null, c.agentId);
  }

  private applySlot(slot: string, json: string): void {
    if (slot === 'sandbox') {
      this.sandboxJson = json;
    } else if (slot === 'guard') {
      this.guardJson = json;
    } else if (slot === 'file') {
      this.fileJson = json;
    } else if (slot === 'scanner') {
      this.scannerJson = json;
    } else {
      this.hostsJson = json;
    }
  }

  private openSheet(mode: string): void {
    this.sheetMode = mode;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  private scannerOptions(): SheetOption[] {
    return [
      optionOf('block', this.t($r('app.string.module_sec_scan_block'))),
      optionOf('warn', this.t($r('app.string.module_sec_scan_warn'))),
      optionOf('off', this.t($r('app.string.module_sec_scan_off')))
    ];
  }

  private async onScannerPick(mode: string): Promise<void> {
    const patch: Record<string, Object> = {};
    patch['mode'] = mode;
    await this.putMerge(PATH_SCANNER, this.scannerJson, patch, 'scanner');
  }

  private hostDefs(): FieldDef[] {
    return [fieldDef('hosts', this.t($r('app.string.module_sec_hosts_field')), 'textarea', false, '',
      this.t($r('app.string.module_sec_hosts_help')))];
  }

  private async saveHosts(values: Record<string, Object>): Promise<void> {
    const raw: string = typeof values['hosts'] === 'string' ? values['hosts'] as string : '';
    const list: string[] = [];
    for (const part of raw.split(',')) {
      const h: string = part.trim();
      if (h.length > 0) {
        list.push(h);
      }
    }
    const patch: Record<string, Object> = {};
    patch['hosts'] = list;
    await this.putMerge(PATH_HOSTS, this.hostsJson, patch, 'hosts');
  }

  // 开关行渲染必须走 @Builder（在 build() 里调用普通方法会被判「不符合 UI 组件语法」）
  @Builder
  switchRow(icon: Resource, label: string, json: string, ok: boolean, slot: string,
    path: string) {
    IosRow({
      icon: icon,
      label: label,
      subtitle: ok ? '' : this.t($r('app.string.module_sec_unsupported')),
      hasSwitch: true,
      switchOn: ok && this.enabledOf(json),
      tappable: ok && !this.busy,
      onSwitch: (on: boolean): void => {
        const patch: Record<string, Object> = {};
        patch['enabled'] = on;
        this.putMerge(path, json, patch, slot);
      }
    })
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
        IosGroup({ title: this.t($r('app.string.module_sec_group_run')) }) {
          this.switchRow($r('sys.symbol.checkmark_shield'), 'Sandbox', this.sandboxJson,
            this.sandboxOk, 'sandbox', PATH_SANDBOX)
          this.switchRow($r('sys.symbol.wrench_and_screwdriver'), 'Tool Guard', this.guardJson,
            this.guardOk, 'guard', PATH_GUARD)
          this.switchRow($r('sys.symbol.doc_text'), 'File Guard', this.fileJson,
            this.fileOk, 'file', PATH_FILE)
        }
        IosGroup({ title: this.t($r('app.string.module_sec_group_chain')) }) {
          IosRow({
            icon: $r('sys.symbol.checkmark_shield'),
            label: 'Skill Scanner',
            subtitle: this.scannerOk ? '' : this.t($r('app.string.module_sec_unsupported')),
            trailing: this.scannerOk ? this.modeLabel() : '',
            tappable: this.scannerOk && !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_SCANNER);
            }
          })
        }
        IosGroup({ title: this.t($r('app.string.module_sec_group_net')) }) {
          IosRow({
            icon: $r('sys.symbol.link'),
            label: this.t($r('app.string.module_sec_hosts')),
            subtitle: this.hostsOk
              ? (this.hostsText().length > 0 ? this.hostsText()
                : this.t($r('app.string.module_sec_hosts_empty')))
              : this.t($r('app.string.module_sec_unsupported')),
            tappable: this.hostsOk && !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_HOSTS);
            }
          })
        }
        ModuleFooter(this.t($r('app.string.module_sec_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_HOSTS ? 560 : 360, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_HOSTS) {
        FieldSheet({
          title: this.t($r('app.string.module_sec_hosts')),
          defs: this.hostDefs(),
          initial: ((): Record<string, Object> => {
            const out: Record<string, Object> = {};
            out['hosts'] = this.hostsText();
            return out;
          })(),
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveHosts(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.sheetMode === MODE_SCANNER) {
        OptionsSheet({
          title: 'Skill Scanner',
          options: this.scannerOptions(),
          current: this.modeOf(this.scannerJson),
          onPick: (v: string): void => {
            this.onScannerPick(v);
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
