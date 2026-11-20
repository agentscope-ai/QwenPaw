/*
 * 工作台模块 · Skills —— 对齐 PR #7378 features/workbench/SkillSettings.tsx。
 *   GET    /api/skills                      → [{name, description, version_text, source, enabled, ...}]
 *   POST   /api/skills/{name}/enable|disable 开关
 *   POST   /api/skills/refresh               重新扫描
 *   POST   /api/skills                       新建（{name, content, config}）
 *   POST   /api/skills/upload?enable=true    导入 ZIP（multipart 字段 file）
 *   DELETE /api/skills/{name}                删除（操作菜单，二次确认）
 * 行副标题取 description（缺省回落 source）；空列表给空态提示。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { atlsRequest, buildMultipart, MultipartBody } from '../services/AtlsTransport';
import { doRequest, jsonArrayOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { PickedFile, pickSingleFile, removeTemp } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { OptionsSheet, SheetOption, optionOf } from './OptionsSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { t } from '../services/I18n';

class SkillItem {
  name: string = '';
  description: string = '';
  source: string = '';
  enabled: boolean = false;
}

const MODE_NONE: string = '';
const MODE_NEW: string = 'new';
const MODE_ACTIONS: string = 'actions';

@Component
export struct ModuleSkills {
  @State skills: SkillItem[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  private target: SkillItem = new SkillItem();
  private zip: PickedFile | null = null;
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
      const resp: http.HttpResponse = await this.send('/skills', http.RequestMethod.GET, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const out: SkillItem[] = [];
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const s: SkillItem = new SkillItem();
        s.name = typeof r['name'] === 'string' ? r['name'] as string : '';
        if (s.name.length === 0) {
          continue;
        }
        s.description = typeof r['description'] === 'string' ? r['description'] as string : '';
        s.source = typeof r['source'] === 'string' ? r['source'] as string : '';
        s.enabled = r['enabled'] === true;
        out.push(s);
      }
      this.skills = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private async post(path: string, body: string | null): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(path, http.RequestMethod.POST, body);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_skill_save_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async toggle(s: SkillItem): Promise<void> {
    await this.post(`/skills/${encodeURIComponent(s.name)}/${s.enabled ? 'disable' : 'enable'}`, null);
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

  private async importZip(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    try {
      const picked: PickedFile | null = await pickSingleFile(ctx, ['.zip']);
      if (picked === null) {
        return;
      }
      this.zip = picked;
      await this.uploadZip(picked);
    } catch (e) {
      this.toast((e as Error).message);
    }
  }

  private async uploadZip(zip: PickedFile): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    this.busy = true;
    try {
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
      const resp: http.HttpResponse = await atlsRequest({
        url: `${c.baseUrl}/api/skills/upload?enable=true`,
        method: http.RequestMethod.POST,
        header: header,
        bodyBytes: multipart.body,
        connectMs: 15000,
        readMs: 120000
      });
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_skill_import_failed'))}：${(e as Error).message}`);
    } finally {
      removeTemp(zip.path);
      this.zip = null;
      this.busy = false;
    }
  }

  private async saveNew(values: Record<string, Object>): Promise<void> {
    const config: Object = this.parseConfig(values['config']);
    await this.post('/skills', JSON.stringify({
      'name': typeof values['name'] === 'string' ? (values['name'] as string).trim() : '',
      'content': typeof values['content'] === 'string' ? values['content'] as string : '',
      'config': config
    }));
  }

  private parseConfig(value: Object): Object {
    if (typeof value !== 'string' || (value as string).trim().length === 0) {
      return JSON.parse('{}') as Object;
    }
    try {
      return JSON.parse(value as string) as Object;
    } catch (e) {
      return JSON.parse('{}') as Object;
    }
  }

  private async remove(): Promise<void> {
    const name: string = this.target.name;
    if (this.busy || name.length === 0) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(
        `/skills/${encodeURIComponent(name)}`, http.RequestMethod.DELETE, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_skill_delete_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private newDefs(): FieldDef[] {
    return [
      fieldDef('name', t($r('app.string.module_skill_field_name')), 'text', true),
      fieldDef('content', t($r('app.string.module_skill_field_content')), 'textarea', true),
      fieldDef('config', t($r('app.string.module_skill_field_config')), 'textarea', false, '',
        t($r('app.string.module_skill_field_config_help')))
    ];
  }

  private actionOptions(): SheetOption[] {
    return [optionOf('delete', t($r('app.string.module_skill_delete')))];
  }

  private async onAction(value: string): Promise<void> {
    if (value === 'delete') {
      await this.remove();
    }
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
        IosGroup({ title: `${t($r('app.string.module_skill_group'))} · ${this.skills.length}` }) {
          IosRow({
            icon: $r('app.media.file_pen'),
            label: t($r('app.string.module_skill_new')),
            subtitle: t($r('app.string.module_skill_new_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(MODE_NEW);
            }
          })
          IosRow({
            icon: $r('app.media.arrow_up_to_line'),
            label: t($r('app.string.module_skill_import')),
            subtitle: t($r('app.string.module_skill_import_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.importZip();
            }
          })
          IosRow({
            icon: $r('app.media.refresh_cw'),
            label: t($r('app.string.module_skill_refresh')),
            tappable: !this.busy,
            onPress: (): void => {
              this.post('/skills/refresh', null);
            }
          })
          ForEach(this.skills, (s: SkillItem) => {
            IosRow({
              icon: $r('app.media.wand_sparkles'),
              label: s.name,
              subtitle: s.description.length > 0 ? s.description
                : (s.source.length > 0 ? s.source : t($r('app.string.module_skill_no_desc'))),
              hasSwitch: true,
              switchOn: s.enabled,
              tappable: true,
              onSwitch: (): void => {
                this.toggle(s);
              },
              onPress: (): void => {
                this.target = s;
                this.openSheet(MODE_ACTIONS);
              }
            })
          }, (s: SkillItem) => s.name)
        }
        if (this.skills.length === 0) {
          ModuleEmpty($r('app.media.wand_sparkles'),
            t($r('app.string.module_skill_empty_title')),
            t($r('app.string.module_skill_empty_subtitle')))
        }
        ModuleFooter(t($r('app.string.module_skill_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(this.sheetMode === MODE_NEW ? 660 : 360, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_NEW) {
        FieldSheet({
          title: t($r('app.string.module_skill_new')),
          defs: this.newDefs(),
          initial: {},
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.saveNew(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.sheetMode === MODE_ACTIONS) {
        OptionsSheet({
          title: this.target.name,
          options: this.actionOptions(),
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
