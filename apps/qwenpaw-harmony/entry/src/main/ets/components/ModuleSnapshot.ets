/*
 * 工作台通用模块快照视图 —— 对齐 PR #7378 features/workbench/SnapshotSettings.tsx
 *                                   + summary.ts（moduleSnapshotItems）。
 * 尚未逐个移植设置项的模块，直接用该模块的后端端点取真实数据并列成行，
 * 不用预览/示例内容；敏感键（password/secret/token/credential/api key/value）一律不展示。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { IosGroup, IosRow } from './IosList';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';

class SnapItem {
  id: string = '';
  title: string = '';
  subtitle: string = '';
}

const TITLE_KEYS: string[] = ['name', 'title', 'id', 'key', 'provider_id', 'session_id'];
const SUBTITLE_KEYS: string[] = ['description', 'status', 'type', 'channel', 'enabled'];

function isRecord(value: Object): boolean {
  return value !== null && value !== undefined && typeof value === 'object' && !Array.isArray(value);
}

function recOf(value: Object): Record<string, Object> {
  return isRecord(value) ? value as Record<string, Object> : {};
}

function strOf(value: Object, fallback: string): string {
  return typeof value === 'string' ? value as string : fallback;
}

// 敏感键不展示（对齐 7378 summary.ts isSensitiveKey）
function isSensitiveKey(key: string): boolean {
  const lower: string = key.toLowerCase();
  const words: string[] = ['password', 'secret', 'token', 'credential', 'value'];
  for (const w of words) {
    if (lower.indexOf(w) >= 0) {
      return true;
    }
  }
  return lower.indexOf('api_key') >= 0 || lower.indexOf('apikey') >= 0;
}

@Component
export struct ModuleSnapshot {
  endpoint: string = '';
  icon: Resource = $r('sys.symbol.doc_text');
  @State items: SnapItem[] = [];
  @State loaded: boolean = false;
  @State error: string = '';
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    this.load();
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      this.error = this.t($r('app.string.module_not_connected'));
      this.loaded = true;
      return;
    }
    this.conn = c;
    const path: string = this.endpoint.replace('{agentId}', encodeURIComponent(c.agentId));
    try {
      const resp: http.HttpResponse = await doRequest(`${c.baseUrl}/api${path}`,
        http.RequestMethod.GET, null, c.token.length > 0 ? c.token : null, c.agentId);
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const payload: Object = JSON.parse(`${resp.result}`) as Object;
      this.items = this.itemsOf(payload);
      this.error = '';
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private itemsOf(payload: Object): SnapItem[] {
    const collection: Object[] | null = this.collectionOf(payload);
    if (collection !== null) {
      const out: SnapItem[] = [];
      const limit: number = Math.min(collection.length, 100);
      for (let i = 0; i < limit; i++) {
        out.push(this.itemOf(collection[i], i));
      }
      return out;
    }
    if (!isRecord(payload)) {
      return [];
    }
    const rec: Record<string, Object> = payload as Record<string, Object>;
    const out: SnapItem[] = [];
    for (const key of Object.keys(rec)) {
      if (isSensitiveKey(key) || out.length >= 100) {
        continue;
      }
      const item: SnapItem = new SnapItem();
      item.id = key;
      item.title = this.humanize(key);
      item.subtitle = this.summarize(rec[key]);
      out.push(item);
    }
    return out;
  }

  // 集合形态：数组本体，或「对象只有一个键且其值是数组」
  private collectionOf(payload: Object): Object[] | null {
    if (Array.isArray(payload)) {
      return payload as Object[];
    }
    if (!isRecord(payload)) {
      return null;
    }
    const rec: Record<string, Object> = payload as Record<string, Object>;
    const keys: string[] = Object.keys(rec);
    if (keys.length === 1 && Array.isArray(rec[keys[0]])) {
      return rec[keys[0]] as Object[];
    }
    return null;
  }

  private itemOf(value: Object, index: number): SnapItem {
    const item: SnapItem = new SnapItem();
    if (!isRecord(value)) {
      item.id = `${index}`;
      item.title = `${value}`;
      return item;
    }
    const rec: Record<string, Object> = value as Record<string, Object>;
    let title: string = '';
    for (const key of TITLE_KEYS) {
      if (typeof rec[key] === 'string') {
        title = rec[key] as string;
        break;
      }
    }
    item.title = title.length > 0 ? title : `${this.t($r('app.string.module_snap_item'))} ${index + 1}`;
    for (const key of SUBTITLE_KEYS) {
      const v: Object = rec[key];
      if (typeof v === 'string' || typeof v === 'boolean') {
        item.subtitle = `${this.humanize(key)} · ${this.summarize(v)}`;
        break;
      }
    }
    item.id = `${item.title}-${index}`;
    return item;
  }

  private summarize(value: Object): string {
    if (typeof value === 'boolean') {
      return (value as boolean) ? this.t($r('app.string.module_snap_enabled'))
        : this.t($r('app.string.module_snap_disabled'));
    }
    if (typeof value === 'string' || typeof value === 'number') {
      return `${value}`;
    }
    if (Array.isArray(value)) {
      return `${(value as Object[]).length} ${this.t($r('app.string.module_snap_items'))}`;
    }
    if (isRecord(value)) {
      const n: number = Object.keys(value as Record<string, Object>).length;
      return `${n} ${this.t($r('app.string.module_snap_fields'))}`;
    }
    return this.t($r('app.string.module_snap_unset'));
  }

  // 下划线键名转可读标题（对齐 7378 humanize）
  private humanize(value: string): string {
    const parts: string[] = value.split('_');
    const out: string[] = [];
    for (const p of parts) {
      if (p.length > 0) {
        out.push(p.charAt(0).toUpperCase() + p.substring(1));
      }
    }
    return out.join(' ');
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
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
      } else if (this.items.length === 0) {
        ModuleEmpty(this.icon,
          this.t($r('app.string.module_snap_empty_title')),
          this.t($r('app.string.module_snap_empty_copy')))
      } else {
        IosGroup({ title: `${this.t($r('app.string.module_snap_group'))} · ${this.items.length}` }) {
          ForEach(this.items, (item: SnapItem) => {
            IosRow({
              icon: this.icon,
              label: item.title,
              subtitle: item.subtitle
            })
          }, (item: SnapItem) => item.id)
        }
        IosGroup({ title: this.t($r('app.string.module_snap_status')) }) {
          IosRow({
            icon: $r('sys.symbol.checkmark'),
            label: this.t($r('app.string.module_snap_synced')),
            trailing: this.conn !== null ? this.conn.agentId : ''
          })
        }
        ModuleFooter(this.t($r('app.string.module_snap_footer')))
      }
    }
    .width('100%')
  }
}
