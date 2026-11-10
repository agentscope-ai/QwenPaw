/*
 * 工作台模块 · Environment 与凭据 —— 对齐 PR #7378 features/workbench/EnvironmentSettings.tsx。
 *   GET    /api/envs            → [{key, value}]
 *   PUT    /api/envs            整表写入（新增/编辑都走这里：提交合并后的 key→value 映射）
 *   DELETE /api/envs/{key}      删除
 * 行只显示键名（值一律「值已隐藏」），编辑表单可见当前值（GET 已返回）。
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
import { t } from '../services/I18n';

class EnvVar {
  key: string = '';
  value: string = '';
}

const MODE_NONE: string = '';
const MODE_FORM: string = 'form';
const MODE_ACTIONS: string = 'actions';

@Component
export struct ModuleEnvironments {
  @State envs: EnvVar[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private target: EnvVar = new EnvVar();
  private editingOldKey: string = '';
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    this.load();
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async send(path: string, method: http.RequestMethod,
    body: string | null): Promise<http.HttpResponse> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error(t($r('app.string.wb_not_connected')));
    }
    return doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
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
      const resp: http.HttpResponse = await this.send('/envs', http.RequestMethod.GET, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const out: EnvVar[] = [];
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const e: EnvVar = new EnvVar();
        e.key = typeof r['key'] === 'string' ? r['key'] as string : '';
        if (e.key.length === 0) {
          continue;
        }
        e.value = typeof r['value'] === 'string' ? r['value'] as string : '';
        out.push(e);
      }
      this.envs = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private openForm(oldKey: string): void {
    let target: EnvVar = new EnvVar();
    for (const e of this.envs) {
      if (e.key === oldKey) {
        target = e;
      }
    }
    this.target = target;
    this.editingOldKey = oldKey;
    this.sheetMode = MODE_FORM;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private openActions(e: EnvVar): void {
    this.target = e;
    this.sheetMode = MODE_ACTIONS;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  private closeSheet(): void {
    this.gate.beginClose();
    this.sheetShown = false;
  }

  // 整表写入：以当前列表为底，编辑时先摘掉旧键（对齐 7378 的 nextMap 口径）
  private async saveForm(values: Record<string, Object>): Promise<void> {
    const key: string = typeof values['key'] === 'string' ? (values['key'] as string).trim() : '';
    const value: string = typeof values['value'] === 'string' ? values['value'] as string : '';
    const map: Record<string, string> = {};
    for (const e of this.envs) {
      if (e.key !== this.editingOldKey) {
        map[e.key] = e.value;
      }
    }
    map[key] = value;
    const resp: http.HttpResponse = await this.send('/envs', http.RequestMethod.PUT,
      JSON.stringify(map));
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
      const resp: http.HttpResponse = await this.send(`/envs/${encodeURIComponent(key)}`,
        http.RequestMethod.DELETE, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_env_delete_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private actions(): SheetOption[] {
    return [
      optionOf('edit', t($r('app.string.module_edit'))),
      optionOf('delete', t($r('app.string.module_env_delete')))
    ];
  }

  private async onAction(value: string): Promise<void> {
    if (value === 'edit') {
      const key: string = this.target.key;
      this.closeSheet();
      this.openForm(key);
      return;
    }
    await this.remove();
  }

  private defs(): FieldDef[] {
    return [
      fieldDef('key', t($r('app.string.module_env_field_key')), 'text', true),
      fieldDef('value', t($r('app.string.module_env_field_value')), 'textarea', true, '',
        t($r('app.string.module_env_field_value_help')))
    ];
  }

  private initial(): Record<string, Object> {
    const out: Record<string, Object> = {};
    if (this.sheetMode !== MODE_FORM || this.editingOldKey.length === 0) {
      return out;
    }
    out['key'] = this.target.key;
    out['value'] = this.target.value;
    return out;
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
        IosGroup({ title: `${t($r('app.string.module_env_group'))} · ${this.envs.length}` }) {
          IosRow({
            icon: $r('app.media.file_pen'),
            label: t($r('app.string.module_env_add')),
            subtitle: t($r('app.string.module_env_add_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.openForm('');
            }
          })
          ForEach(this.envs, (e: EnvVar) => {
            IosRow({
              icon: $r('app.media.shield_check'),
              label: e.key,
              subtitle: t($r('app.string.module_env_hidden')),
              tappable: !this.busy,
              onPress: (): void => {
                this.openActions(e);
              }
            })
          }, (e: EnvVar) => e.key)
        }
        if (this.envs.length === 0) {
          ModuleEmpty($r('app.media.shield_check'),
            t($r('app.string.module_env_empty_title')),
            t($r('app.string.module_env_empty_subtitle')))
        }
        ModuleFooter(t($r('app.string.module_env_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_FORM ? 620 : 360, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_FORM) {
        FieldSheet({
          title: this.editingOldKey.length > 0
            ? `${t($r('app.string.module_edit'))} ${this.editingOldKey}`
            : t($r('app.string.module_env_add')),
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
          title: this.target.key,
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
