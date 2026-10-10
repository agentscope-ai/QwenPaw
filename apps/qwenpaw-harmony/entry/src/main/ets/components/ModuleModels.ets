/*
 * 工作台模块 · Models 与 Providers —— 对齐 PR #7378 features/workbench/ModelsSettings.tsx
 *   与 LocalModelSettings.tsx。
 *   GET /api/models               → [{id,name,enabled,base_url,api_key,model_count,...}]
 *   PUT /api/models/{id}/config   → 启用/停用（以 GET 原文整表回写，只覆盖 enabled，不丢未展示字段）
 *   GET /api/models/active        → {active_llm:{provider_id,model}, effective_max_input_length}
 *   GET /api/local-models/server  → {available,installable,installed,port,model_name,message}
 *   GET /api/local-models/models  → [{id,name,released_at,supports_multimodal,...}]
 * 某一路 404 → 该组显示「当前 QwenPaw 不支持」（对齐 7378 的 unsupported 口径）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';

const PATH_PROVIDERS: string = '/models';
const PATH_ACTIVE: string = '/models/active';
const PATH_LM_SERVER: string = '/local-models/server';
const PATH_LM_MODELS: string = '/local-models/models';

class ProviderRow {
  id: string = '';
  name: string = '';
  enabled: boolean = false;
  baseUrl: string = '';
  modelCount: number = -1;
  raw: Record<string, Object> = {} as Record<string, Object>;
}

class LocalModelRow {
  id: string = '';
  name: string = '';
  releasedAt: string = '';
}

@Component
export struct ModuleModels {
  @State providers: ProviderRow[] = [];
  @State localModels: LocalModelRow[] = [];
  @State activeJson: string = '{}';
  @State serverJson: string = '{}';
  @State providersOk: boolean = false;
  @State activeOk: boolean = false;
  @State lmOk: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
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
      const p: http.HttpResponse = await this.send(PATH_PROVIDERS, http.RequestMethod.GET, null);
      this.providersOk = p.responseCode >= 200 && p.responseCode < 300;
      this.providers = this.providersOk ? this.parseProviders(p) : [];

      const a: http.HttpResponse = await this.send(PATH_ACTIVE, http.RequestMethod.GET, null);
      this.activeOk = a.responseCode >= 200 && a.responseCode < 300;
      this.activeJson = this.activeOk ? JSON.stringify(jsonOf(a)) : '{}';

      const s: http.HttpResponse = await this.send(PATH_LM_SERVER, http.RequestMethod.GET, null);
      const m: http.HttpResponse = await this.send(PATH_LM_MODELS, http.RequestMethod.GET, null);
      const sOk: boolean = s.responseCode >= 200 && s.responseCode < 300;
      const mOk: boolean = m.responseCode >= 200 && m.responseCode < 300;
      this.lmOk = sOk || mOk;
      this.serverJson = sOk ? JSON.stringify(jsonOf(s)) : '{}';
      this.localModels = mOk ? this.parseLocalModels(m) : [];

      if (!this.providersOk && !this.activeOk && !this.lmOk) {
        this.error = this.t($r('app.string.module_models_unsupported'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private parseProviders(resp: http.HttpResponse): ProviderRow[] {
    const out: ProviderRow[] = [];
    for (const item of jsonArrayOf(resp)) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: ProviderRow = new ProviderRow();
      row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
      if (row.id.length === 0) {
        continue;
      }
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
      row.enabled = r['enabled'] === true;
      row.baseUrl = typeof r['base_url'] === 'string' ? r['base_url'] as string : '';
      row.modelCount = typeof r['model_count'] === 'number' ? r['model_count'] as number : -1;
      row.raw = r;
      out.push(row);
    }
    return out;
  }

  private parseLocalModels(resp: http.HttpResponse): LocalModelRow[] {
    const out: LocalModelRow[] = [];
    for (const item of jsonArrayOf(resp)) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: LocalModelRow = new LocalModelRow();
      row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
      if (row.id.length === 0) {
        continue;
      }
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
      row.releasedAt = typeof r['released_at'] === 'string' ? r['released_at'] as string : '';
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

  private activeField(key: string): string {
    const llm: Object = this.recOf(this.activeJson)['active_llm'];
    if (llm === undefined || llm === null) {
      return '—';
    }
    const v: Object = (llm as Record<string, Object>)[key];
    return typeof v === 'string' ? v as string : '—';
  }

  private maxInput(): string {
    const v: Object = this.recOf(this.activeJson)['effective_max_input_length'];
    return typeof v === 'number' ? `${v}` : '—';
  }

  private serverField(key: string): string {
    const v: Object = this.recOf(this.serverJson)[key];
    if (typeof v === 'string') {
      return v as string;
    }
    if (typeof v === 'boolean') {
      return v ? this.t($r('app.string.module_models_yes')) : this.t($r('app.string.module_models_no'));
    }
    if (typeof v === 'number') {
      return `${v}`;
    }
    return '—';
  }

  private subtitleOf(row: ProviderRow): string {
    const parts: string[] = [];
    if (row.baseUrl.length > 0) {
      parts.push(row.baseUrl);
    }
    if (row.modelCount >= 0) {
      parts.push(`${row.modelCount} 个模型`);
    }
    return parts.join(' · ');
  }

  private async toggle(row: ProviderRow): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      // 整表回写：以 GET 原文档为底，只覆盖 enabled（未展示字段原样带回）
      const body: Record<string, Object> = row.raw;
      body['enabled'] = !row.enabled;
      const resp: http.HttpResponse = await this.send(`/models/${encodeURIComponent(row.id)}/config`,
        http.RequestMethod.PUT, JSON.stringify(body));
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_models_save_failed'))}：${(e as Error).message}`);
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
        IosGroup({ title: this.t($r('app.string.module_models_group_active')) }) {
          IosRow({
            icon: $r('sys.symbol.bolt'),
            label: this.t($r('app.string.module_models_active_provider')),
            trailing: this.activeOk ? this.activeField('provider_id')
              : this.t($r('app.string.module_models_na'))
          })
          IosRow({
            icon: $r('sys.symbol.archivebox'),
            label: this.t($r('app.string.module_models_active_model')),
            trailing: this.activeOk ? this.activeField('model')
              : this.t($r('app.string.module_models_na'))
          })
          IosRow({
            icon: $r('sys.symbol.arrow_left_arrow_right'),
            label: this.t($r('app.string.module_models_max_input')),
            trailing: this.activeOk ? this.maxInput() : this.t($r('app.string.module_models_na'))
          })
        }
        IosGroup({ title: `${this.t($r('app.string.module_models_group_providers'))} · ${this.providers.length}` }) {
          ForEach(this.providers, (row: ProviderRow) => {
            IosRow({
              icon: $r('sys.symbol.cloud'),
              label: row.name,
              subtitle: this.subtitleOf(row),
              hasSwitch: true,
              switchOn: row.enabled,
              tappable: this.providersOk && !this.busy,
              onSwitch: (): void => {
                this.toggle(row);
              }
            })
          }, (row: ProviderRow) => row.id)
        }
        IosGroup({ title: `${this.t($r('app.string.module_models_group_local'))} · ${this.localModels.length}` }) {
          IosRow({
            icon: $r('sys.symbol.desktop'),
            label: this.t($r('app.string.module_models_local_server')),
            subtitle: this.lmOk ? this.serverField('message')
              : this.t($r('app.string.module_models_unsupported')),
            trailing: this.lmOk ? this.serverField('installed') : ''
          })
          ForEach(this.localModels, (row: LocalModelRow) => {
            IosRow({
              icon: $r('sys.symbol.archivebox'),
              label: row.name,
              subtitle: row.releasedAt
            })
          }, (row: LocalModelRow) => row.id)
        }
        if (this.providersOk && this.providers.length === 0) {
          ModuleEmpty($r('sys.symbol.cloud'),
            this.t($r('app.string.module_models_empty_title')),
            this.t($r('app.string.module_models_empty_subtitle')))
        }
        ModuleFooter(this.t($r('app.string.module_models_footer')))
      }
    }
    .width('100%')
  }
}
