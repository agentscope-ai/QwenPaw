/*
 * 工作台模块 · QwenPaw Hub —— 对齐 PR #7378 features/workbench/HubSettings.tsx。
 *   GET  /api/hub/healthz                    → {status,...}
 *   GET  /api/hub/me                         → {id,name,role,...}
 *   GET  /api/hub/runtimes?page_size=100     → {items:[{id,name,status,...}]}
 *   GET  /api/hub/admin/overview             → 管理员概览
 *   POST /api/hub/me/runtime/restart         → 重启个人 Runtime
 * 某一路 404（该 QwenPaw 未启用 Hub）→ 该组显示「当前 QwenPaw 不支持」；
 * 全部 404 → 整页提示未启用 Hub。字段缺失一律显示「—」，不猜字段。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonOf } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';

const PATH_HEALTH: string = '/hub/healthz';
const PATH_ME: string = '/hub/me';
const PATH_RUNTIMES: string = '/hub/runtimes?page_size=100';
const PATH_RESTART: string = '/hub/me/runtime/restart';

class RuntimeRow {
  id: string = '';
  name: string = '';
  status: string = '';
}

@Component
export struct ModuleHub {
  @State healthJson: string = '{}';
  @State meJson: string = '{}';
  @State runtimes: RuntimeRow[] = [];
  @State healthOk: boolean = false;
  @State meOk: boolean = false;
  @State runtimesOk: boolean = false;
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
      const h: http.HttpResponse = await this.send(PATH_HEALTH, http.RequestMethod.GET, null);
      this.healthOk = h.responseCode >= 200 && h.responseCode < 300;
      this.healthJson = this.healthOk ? JSON.stringify(jsonOf(h)) : '{}';

      const m: http.HttpResponse = await this.send(PATH_ME, http.RequestMethod.GET, null);
      this.meOk = m.responseCode >= 200 && m.responseCode < 300;
      this.meJson = this.meOk ? JSON.stringify(jsonOf(m)) : '{}';

      const r: http.HttpResponse = await this.send(PATH_RUNTIMES, http.RequestMethod.GET, null);
      this.runtimesOk = r.responseCode >= 200 && r.responseCode < 300;
      this.runtimes = this.runtimesOk ? this.parseRuntimes(r) : [];

      if (!this.healthOk && !this.meOk && !this.runtimesOk) {
        this.error = this.t($r('app.string.module_hub_unsupported'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private parseRuntimes(resp: http.HttpResponse): RuntimeRow[] {
    const out: RuntimeRow[] = [];
    const raw: Object = jsonOf(resp)['items'];
    if (raw === undefined || raw === null || !Array.isArray(raw)) {
      return out;
    }
    for (const item of raw as Object[]) {
      const rec: Record<string, Object> = item as Record<string, Object>;
      const row: RuntimeRow = new RuntimeRow();
      const id: Object = rec['id'];
      row.id = typeof id === 'string' ? id as string : '';
      if (row.id.length === 0) {
        continue;
      }
      const name: Object = rec['name'];
      row.name = typeof name === 'string' ? name as string : row.id;
      const st: Object = rec['status'];
      row.status = typeof st === 'string' ? st as string : '';
      out.push(row);
    }
    return out;
  }

  private field(json: string, key: string): string {
    let rec: Record<string, Object> = {} as Record<string, Object>;
    try {
      rec = JSON.parse(json) as Record<string, Object>;
    } catch (e) {
      rec = {} as Record<string, Object>;
    }
    const v: Object = rec[key];
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

  private async restart(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      const resp: http.HttpResponse = await this.send(PATH_RESTART, http.RequestMethod.POST, null);
      if (resp.responseCode === 404) {
        this.toast(this.t($r('app.string.module_hub_unsupported')));
        return;
      }
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      this.toast(this.t($r('app.string.module_hub_restarted')));
      await this.load();
    } catch (e) {
      this.toast(`${this.t($r('app.string.module_ext_failed'))}：${(e as Error).message}`);
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
        IosGroup({ title: this.t($r('app.string.module_hub_group_health')) }) {
          IosRow({
            icon: $r('sys.symbol.bolt'),
            label: this.t($r('app.string.module_hub_status')),
            trailing: this.healthOk ? this.field(this.healthJson, 'status')
              : this.t($r('app.string.module_models_na'))
          })
        }
        IosGroup({ title: this.t($r('app.string.module_hub_group_me')) }) {
          IosRow({
            icon: $r('sys.symbol.person'),
            label: this.t($r('app.string.module_hub_name')),
            trailing: this.meOk ? this.field(this.meJson, 'name')
              : this.t($r('app.string.module_models_na'))
          })
          IosRow({
            icon: $r('sys.symbol.link'),
            label: this.t($r('app.string.module_hub_id')),
            trailing: this.meOk ? this.field(this.meJson, 'id')
              : this.t($r('app.string.module_models_na'))
          })
          IosRow({
            icon: $r('sys.symbol.checkmark_shield'),
            label: this.t($r('app.string.module_hub_role')),
            trailing: this.meOk ? this.field(this.meJson, 'role')
              : this.t($r('app.string.module_models_na'))
          })
        }
        IosGroup({ title: `${this.t($r('app.string.module_hub_group_runtimes'))} · ${this.runtimes.length}` }) {
          if (this.runtimesOk) {
            ForEach(this.runtimes, (row: RuntimeRow) => {
              IosRow({
                icon: $r('sys.symbol.desktop'),
                label: row.name,
                subtitle: row.status
              })
            }, (row: RuntimeRow) => row.id)
          } else {
            IosRow({
              icon: $r('sys.symbol.desktop'),
              label: this.t($r('app.string.module_hub_group_runtimes')),
              subtitle: this.t($r('app.string.module_hub_unsupported'))
            })
          }
        }
        IosGroup({ title: this.t($r('app.string.module_hub_group_actions')) }) {
          IosRow({
            icon: $r('sys.symbol.arrow_clockwise'),
            label: this.t($r('app.string.module_hub_restart')),
            subtitle: this.t($r('app.string.module_hub_restart_hint')),
            tappable: !this.busy,
            onPress: (): void => {
              this.restart();
            }
          })
        }
        ModuleFooter(this.t($r('app.string.module_hub_footer')))
      }
    }
    .width('100%')
  }
}
