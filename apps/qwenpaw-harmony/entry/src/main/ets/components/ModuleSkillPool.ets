/*
 * 工作台模块 · Skill Pool —— 对齐 PR #7378 features/workbench/SkillPoolSettings.tsx。
 *   GET  /api/skills/pool                     → [{name, description, source, content, tags, config, ...}]
 *   POST /api/skills/pool/create              {name, content, config} 新建
 *   PUT  /api/skills/pool/save                {name, content, config, source_name, overwrite:false} 覆盖保存
 *   PUT  /api/skills/pool/{name}/tags         tags 数组（独立接口，紧随保存调用）
 *   POST /api/skills/pool/refresh             重新扫描
 *   POST /api/skills/pool/upload-zip          导入 ZIP（multipart 字段 file）
 * 表单字段：name / content / tags（逗号分隔 → 数组）/ config（JSON）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { PickedFile, pickSingleFile, removeTemp } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';

class PoolSkill {
  name: string = '';
  description: string = '';
  source: string = '';
  content: string = '';
  tags: string = '';        // 逗号分隔（表单口径）
  config: string = '{}';    // JSON 文本
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

@Component
export struct ModuleSkillPool {
  @State skills: PoolSkill[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State sheetShown: boolean = false;
  @State editingName: string = '';     // '' = 新建
  private editing: PoolSkill = new PoolSkill();
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
      const resp: http.HttpResponse = await this.send('/skills/pool', http.RequestMethod.GET, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const out: PoolSkill[] = [];
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const s: PoolSkill = new PoolSkill();
        s.name = strOf(r['name'], '');
        if (s.name.length === 0) {
          continue;
        }
        s.description = strOf(r['description'], '');
        s.source = strOf(r['source'], '');
        s.content = strOf(r['content'], '');
        const tags: string[] = [];
        const raw: Object = r['tags'];
        if (Array.isArray(raw)) {
          for (const tag of raw as Object[]) {
            if (typeof tag === 'string') {
              tags.push(tag as string);
            }
          }
        }
        s.tags = tags.join(', ');
        const config: Object = r['config'];
        s.config = JSON.stringify(config !== undefined && config !== null ? config : {});
        out.push(s);
      }
      this.skills = out;
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private openSheet(skill: PoolSkill | null): void {
    this.editing = skill !== null ? skill : new PoolSkill();
    this.editingName = skill !== null ? skill.name : '';
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
      fieldDef('name', this.t($r('app.string.module_pool_field_name')), 'text', true),
      fieldDef('content', this.t($r('app.string.module_pool_field_content')), 'textarea', true),
      fieldDef('tags', this.t($r('app.string.module_pool_field_tags')), 'text', false, '',
        this.t($r('app.string.module_pool_field_tags_help'))),
      fieldDef('config', this.t($r('app.string.module_pool_field_config')), 'textarea', false, '',
        this.t($r('app.string.module_pool_field_config_help')))
    ];
  }

  private initial(): Record<string, Object> {
    const out: Record<string, Object> = {};
    if (this.editingName.length === 0) {
      out['config'] = '{}';
      return out;
    }
    out['name'] = this.editing.name;
    out['content'] = this.editing.content;
    out['tags'] = this.editing.tags;
    out['config'] = this.editing.config;
    return out;
  }

  private async save(values: Record<string, Object>): Promise<void> {
    const name: string = strOf(values['name'], '').trim();
    const payload: Record<string, Object> = {};
    payload['name'] = name;
    payload['content'] = strOf(values['content'], '');
    payload['config'] = this.parseConfig(values['config']);
    const isEdit: boolean = this.editingName.length > 0;
    if (isEdit) {
      payload['source_name'] = this.editingName;
      payload['overwrite'] = false;
    }
    const resp: http.HttpResponse = await this.send(
      isEdit ? '/skills/pool/save' : '/skills/pool/create',
      isEdit ? http.RequestMethod.PUT : http.RequestMethod.POST,
      JSON.stringify(payload));
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
    // tags 走独立接口（对齐 7378：保存成功后再 PUT，非空才调用）
    const tags: string[] = [];
    for (const raw of strOf(values['tags'], '').split(',')) {
      const tag: string = raw.trim();
      if (tag.length > 0) {
        tags.push(tag);
      }
    }
    if (tags.length > 0) {
      const tagResp: http.HttpResponse = await this.send(
        `/skills/pool/${encodeURIComponent(name)}/tags`, http.RequestMethod.PUT,
        JSON.stringify(tags));
      if (tagResp.responseCode < 200 || tagResp.responseCode >= 300) {
        throw new Error(`HTTP ${tagResp.responseCode}`);
      }
    }
    await this.load();
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

  private async refresh(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send('/skills/pool/refresh',
        http.RequestMethod.POST, null);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_pool_refresh_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  private async importZip(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    let picked: PickedFile | null = null;
    try {
      picked = await pickSingleFile(ctx, ['.zip']);
    } catch (e) {
      this.toast((e as Error).message);
      return;
    }
    if (picked === null) {
      return;
    }
    const c: QpConnection | null = this.conn;
    if (c === null) {
      removeTemp(picked.path);
      return;
    }
    this.busy = true;
    try {
      const form: http.MultiFormData = {
        name: 'file',
        contentType: 'application/zip',
        remoteFileName: picked.name,
        filePath: picked.path
      };
      const header: Record<string, Object> = {
        'Content-Type': 'multipart/form-data',
        'Accept': 'application/json'
      };
      if (c.token.length > 0) {
        header['Authorization'] = `Bearer ${c.token}`;
      }
      if (c.agentId.length > 0) {
        header['X-Agent-Id'] = c.agentId;
      }
      const options: http.HttpRequestOptions = {
        method: http.RequestMethod.POST,
        header: header,
        multiFormDataList: [form],
        connectTimeout: 15000,
        readTimeout: 120000,
        expectDataType: http.HttpDataType.STRING
      };
      const req: http.HttpRequest = http.createHttp();
      try {
        const resp: http.HttpResponse = await req.request(
          `${c.baseUrl}/api/skills/pool/upload-zip`, options);
        if (resp.responseCode < 200 || resp.responseCode >= 300) {
          throw new Error(`HTTP ${resp.responseCode}`);
        }
      } finally {
        req.destroy();
      }
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_pool_import_failed'))}：${(e as Error).message}`);
    } finally {
      removeTemp(picked.path);
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
        IosGroup({ title: `Skill Pool · ${this.skills.length}` }) {
          IosRow({
            icon: $r('sys.symbol.doc_plaintext_and_pencil'),
            label: this.t($r('app.string.module_pool_new')),
            tappable: !this.busy,
            onPress: (): void => {
              this.openSheet(null);
            }
          })
          IosRow({
            icon: $r('sys.symbol.arrow_up_to_line'),
            label: this.t($r('app.string.module_pool_import')),
            subtitle: this.t($r('app.string.module_pool_import_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.importZip();
            }
          })
          IosRow({
            icon: $r('sys.symbol.arrow_clockwise'),
            label: this.t($r('app.string.module_pool_refresh')),
            tappable: !this.busy,
            onPress: (): void => {
              this.refresh();
            }
          })
          ForEach(this.skills, (s: PoolSkill) => {
            IosRow({
              icon: $r('sys.symbol.list_book'),
              label: s.name,
              subtitle: s.description.length > 0 ? s.description
                : (s.source.length > 0 ? s.source : this.t($r('app.string.module_pool_shared'))),
              tappable: !this.busy,
              onPress: (): void => {
                this.openSheet(s);
              }
            })
          }, (s: PoolSkill) => s.name)
        }
        if (this.skills.length === 0) {
          ModuleEmpty($r('sys.symbol.list_book'),
            this.t($r('app.string.module_pool_empty_title')),
            this.t($r('app.string.module_pool_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_pool_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.editSheet(),
      moduleSheetOptions(700, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  @Builder
  editSheet() {
    Column() {
      FieldSheet({
        title: this.editingName.length > 0
          ? `${this.t($r('app.string.module_pool_edit'))} ${this.editingName}`
          : this.t($r('app.string.module_pool_new')),
        defs: this.defs(),
        initial: this.initial(),
        onSave: async (values: Record<string, Object>): Promise<void> => {
          await this.save(values);
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
