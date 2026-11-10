/*
 * 工作台模块 · 扩展 —— 对齐 PR #7378 features/workbench/ExtensionsSettings.tsx。
 *   GET    /api/plugins                       → [{id,name,version,description,plugin_type,loaded,...}]
 *   GET    /api/pawapps                       → {apps:[{id,name,version,description,status,...}]}
 *   POST   /api/plugins/install               → {source:<ZIP URL>, force:false}
 *   POST   /api/plugins/upload                → multipart file（设备 ZIP 包，须 .zip 结尾）→ 安装（热加载免重启）
 *   DELETE /api/plugins/{id}                  → 卸载
 *   POST   /api/market/search                 → {query, provider_pages, limit, lang} → {results, errors}
 *   POST   /api/skills/hub/install/start      → {bundle_url, version, enable:true} → {task_id}
 *   GET    /api/skills/hub/install/status/{id} → {status}（安装进度轮询）
 * 两组取数任一 404 → 该组显示「当前 QwenPaw 不支持」；两组都 404 才整页报不支持。
 *
 * 结构：Skill 市场（搜索 + 安装）→ App Center（点开 PawApp 详情）
 * → 本地插件（安装动作：设备 ZIP 包上传安装 POST /api/plugins/upload + 按 URL 安装）
 * → 本地应用（设备安装的插件，离线运行：ZIP 安装 / 运行 / 卸载，services/LocalPluginStore，
 *   连接与本地形态共用、与远端连接状态无关）
 * → 已安装扩展（/plugins 全量列表 + 卸载）→ 通知接入（连接与本地形态共用）。
 *
 * 插件语义区分：「本地插件」= 对当前 QwenPaw 服务端的安装动作（设备 ZIP / URL）；
 * 「远端 PawApp」= QwenPaw 提供的前端扩展应用（services/RemotePawApps 注册表，只浏览详情，
 * 不提供安装）；「本地应用」= 装在本机离线运行的前端插件（本地安装与远端安装是两套环境，
 * 互不提示「已存在」）；「已安装扩展」= 服务端 /plugins 返回的全部已装插件。
 *
 * 本地形态（未连接远端 QwenPaw）：服务端取数不可用，但工作台入口仍要可用 —— 整页不再报
 * 「未连接」死胡同，改为列出已知远端 PawApp（services/RemotePawApps 注册表，需 QwenPaw
 * 后端运行、本地形态只浏览）+ 本地应用（离线安装 / 运行 / 卸载，纯本地文件操作）+ 通知接入行
 * （跳通知设置页）。本地形态无任何网络请求。
 */

import { BusinessError } from '@kit.BasicServicesKit';
import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { doRequest, jsonArrayOf, jsonOf, uploadFile } from '../services/ConnectionService';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import { pickSingleFile, removeTemp, PickedFile } from '../services/AttachmentPicker';
import { IosGroup, IosRow } from './IosList';
import { FieldDef, FieldSheet, fieldDef } from './FieldSheet';
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from './ModuleStates';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { requestNotifications, requestPawApp, requestLocalPawApp } from '../services/AppEvents';
import { LocalPluginStore, LocalPluginInfo, ERR_ZIP, ERR_ROOT, ERR_ID,
  ERR_ENTRY, ERR_ENTRY_MISSING, ERR_EXISTS } from '../services/LocalPluginStore';
import { RemotePawAppEntry, REMOTE_PAWAPPS } from '../services/RemotePawApps';
import { UiTokens } from '../theme/UiTokens';

import { accentColor } from '../theme/Accent';
import { PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { t } from '../services/I18n';

const PATH_PLUGINS: string = '/plugins';
const PATH_PAWAPPS: string = '/pawapps';

const MODE_NONE: string = '';
const MODE_INSTALL: string = 'install';
const MODE_LOCAL: string = 'local';

// 安装轮询：每次 500ms，最多 120 次（约 60s，对齐 7378 waitForInstall）
const POLL_INTERVAL_MS: number = 500;
const POLL_MAX: number = 120;

class PluginRow {
  id: string = '';
  name: string = '';
  version: string = '';
  description: string = '';
  pluginType: string = '';
  loaded: boolean = false;
  isApp: boolean = false;
}

class AppRow {
  id: string = '';
  name: string = '';
  version: string = '';
  description: string = '';
  status: string = '';
  // /api/pawapps 的 entry_page：插件自声明的前端入口路由（打开详情页的 Web 目标路径）
  entryPage: string = '';
}

class MarketRow {
  source: string = '';
  slug: string = '';
  name: string = '';
  description: string = '';
  sourceUrl: string = '';
  version: string = '';
  author: string = '';
}

@Component
export struct ModuleExtensions {
  @State plugins: PluginRow[] = [];
  @State apps: AppRow[] = [];
  @State pluginsOk: boolean = false;
  @State appsOk: boolean = false;
  @State loaded: boolean = false;
  @State error: string = '';
  @State busy: boolean = false;
  @State query: string = '';
  @State searching: boolean = false;
  @State searched: boolean = false;
  @State results: MarketRow[] = [];
  // 正在安装的市场项 slug（行上显示「安装中」；非空时屏蔽重复安装）
  @State installing: string = '';
  // 本地插件 ZIP 上传安装进行中（行上显示「安装中」；屏蔽重复安装）
  @State localInstalling: boolean = false;
  // 本地应用（设备安装的插件，离线运行）：注册表 + 安装/卸载动作进行中标志
  @State localApps: LocalPluginInfo[] = [];
  @State appBusy: boolean = false;
  @State sheetShown: boolean = false;
  @State sheetMode: string = MODE_NONE;
  @StorageLink('appIsDark') isDark: boolean = false;
  // 本地形态（未连接远端）：不取数，只展示远端 PawApp 注册表与通知接入
  @State localMode: boolean = false;
  // 远端 PawApp 详情面板当前展示的条目（MODE_LOCAL 时使用）
  @State localDetail: RemotePawAppEntry | null = null;
  private gate: SheetGate = new SheetGate();
  private conn: QpConnection | null = null;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.loadLocalApps();
    this.load();
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private accent(): ResourceColor {
    return accentColor(this.isDark);
  }

  private async send(path: string, method: http.RequestMethod,
    body: string | null): Promise<http.HttpResponse> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error(t($r('app.string.module_not_connected')));
    }
    return doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
  }

  // 两组取数并发（旧写法顺序 await，慢一倍）：任一 404 只降级该组，两组都不可用才整页报不支持
  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      // 未连接 → 本地形态（不整页报错）：App 本地前端扩展插件 + 通知接入
      this.localMode = true;
      this.loaded = true;
      return;
    }
    this.conn = c;
    try {
      const pluginsReq: Promise<http.HttpResponse> =
        this.send(PATH_PLUGINS, http.RequestMethod.GET, null);
      const appsReq: Promise<http.HttpResponse> =
        this.send(PATH_PAWAPPS, http.RequestMethod.GET, null);
      const p: http.HttpResponse = await pluginsReq;
      this.pluginsOk = p.responseCode >= 200 && p.responseCode < 300;
      this.plugins = this.pluginsOk ? this.parseList(p) : [];

      const a: http.HttpResponse = await appsReq;
      this.appsOk = a.responseCode >= 200 && a.responseCode < 300;
      this.apps = this.appsOk ? this.parseApps(a) : [];

      if (!this.pluginsOk && !this.appsOk) {
        this.error = t($r('app.string.module_ext_unsupported'));
      } else {
        this.error = '';
      }
    } catch (e) {
      this.error = (e as Error).message;
    }
    this.loaded = true;
  }

  private parseList(resp: http.HttpResponse): PluginRow[] {
    const out: PluginRow[] = [];
    for (const item of jsonArrayOf(resp)) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: PluginRow = new PluginRow();
      row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
      row.version = typeof r['version'] === 'string' ? r['version'] as string : '';
      row.description = typeof r['description'] === 'string' ? r['description'] as string : '';
      row.pluginType = typeof r['plugin_type'] === 'string' ? r['plugin_type'] as string : 'plugin';
      row.loaded = r['loaded'] === true;
      row.isApp = row.pluginType === 'app';
      if (row.id.length > 0) {
        out.push(row);
      }
    }
    return out;
  }

  private parseApps(resp: http.HttpResponse): AppRow[] {
    const out: AppRow[] = [];
    const apps: Object = jsonOf(resp)['apps'];
    if (apps === undefined || apps === null || !Array.isArray(apps)) {
      return out;
    }
    for (const item of apps as Object[]) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: AppRow = new AppRow();
      row.id = typeof r['id'] === 'string' ? r['id'] as string : '';
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.id;
      row.version = typeof r['version'] === 'string' ? r['version'] as string : '';
      row.description = typeof r['description'] === 'string' ? r['description'] as string : '';
      row.status = typeof r['status'] === 'string' ? r['status'] as string : '';
      row.entryPage = typeof r['entry_page'] === 'string' ? r['entry_page'] as string : '';
      if (row.id.length > 0) {
        out.push(row);
      }
    }
    return out;
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

  private installDefs(): FieldDef[] {
    return [fieldDef('source', t($r('app.string.module_ext_source')), 'text', true, '',
      t($r('app.string.module_ext_source_help')))];
  }

  // 安装（URL）：载荷对齐 7378 —— {source:<ZIP URL>, force:false}
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
    this.toast(t($r('app.string.module_ext_installed')));
    await this.load();
  }

  // 卸载：点行 → 确认对话框（对齐 7378 removePlugin）
  private confirmUninstall(row: PluginRow): void {
    if (this.busy) {
      return;
    }
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.module_ext_uninstall_confirm')),
      message: row.version.length > 0 ? `${row.name} · ${row.version}` : row.name,
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.module_ext_uninstall_action')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.uninstall(row.id);
        }
      }
    });
  }

  private async uninstall(id: string): Promise<void> {
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
      this.toast(t($r('app.string.module_ext_uninstalled')));
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_ext_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  // 从设备 ZIP 安装：选设备上的插件 ZIP（单选 + 后缀过滤）→ 拷贝进沙箱 → 上传安装
  private installLocalZip(): void {
    if (this.localInstalling || this.busy) {
      return;
    }
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    pickSingleFile(ctx, [t($r('app.string.module_ext_local_zip_filter'))])
      .then((picked: PickedFile | null): void => {
        if (picked === null) {
          return; // 用户取消选择
        }
        this.uploadLocalZip(picked);
      })
      .catch((e: Error): void => {
        this.toast(`${t($r('app.string.module_ext_failed'))}：${e.message}`);
      });
  }

  // 上传设备 ZIP 包安装（multipart file 字段；服务端按文件名校验 .zip 后缀并热加载）
  private async uploadLocalZip(picked: PickedFile): Promise<void> {
    if (!picked.name.toLowerCase().endsWith('.zip')) {
      this.toast(t($r('app.string.module_ext_local_zip_only')));
      return;
    }
    const c: QpConnection | null = this.conn;
    if (c === null) {
      this.toast(t($r('app.string.module_not_connected')));
      return;
    }
    this.localInstalling = true;
    try {
      const resp: http.HttpResponse = await uploadFile(
        `${c.baseUrl}/api/plugins/upload`,
        c.token.length > 0 ? c.token : null, c.agentId, picked.path, picked.name, 'application/zip');
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(this.uploadErrorOf(resp, resp.responseCode));
      }
      const data: Record<string, Object> = jsonOf(resp);
      const name: string = typeof data['name'] === 'string' ? data['name'] as string : picked.name;
      const ver: string = typeof data['version'] === 'string' ? data['version'] as string : '';
      this.toast(`${t($r('app.string.module_ext_local_installed'))}：${name}${ver.length > 0 ? ' · ' + ver : ''}`);
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.module_ext_failed'))}：${(e as Error).message}`);
    } finally {
      this.localInstalling = false;
      removeTemp(picked.path);
    }
  }

  // 上传失败文案：FastAPI 错误体 {detail} 透出原因（400 非 zip / 409 已加载 / 503 loader 未就绪）
  private uploadErrorOf(resp: http.HttpResponse, code: number): string {
    const result: Object = resp.result;
    if (typeof result === 'string') {
      try {
        const data: Record<string, Object> = JSON.parse(result) as Record<string, Object>;
        if (typeof data['detail'] === 'string' && (data['detail'] as string).length > 0) {
          return data['detail'] as string;
        }
      } catch (e) {
        // 非 JSON 错误体 → 落回 HTTP 码
      }
    }
    return `HTTP ${code}`;
  }

  // ==================== 本地应用（设备安装，离线运行；services/LocalPluginStore） ====================

  // 本地应用注册表（同步读盘；进页与安装/卸载成功后调用）
  private loadLocalApps(): void {
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      this.localApps = LocalPluginStore.list(ctx);
    } catch (e) {
      this.localApps = [];
    }
  }

  // 运行本地应用：本组件拿不到导航栈，交事件总线转给根页 push localpawapp 路由
  private runLocalApp(info: LocalPluginInfo): void {
    requestLocalPawApp(info.id, info.name, info.entry);
  }

  // 从设备 ZIP 安装（本地离线安装：选 ZIP → LocalPluginStore.installFromZip；
  // 临时文件清理由存储层自理，失败抛错误码由 UI 层取 i18n 文案）
  private installAppZip(): void {
    if (this.appBusy || this.busy) {
      return;
    }
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    pickSingleFile(ctx, [t($r('app.string.module_ext_local_zip_filter'))])
      .then((picked: PickedFile | null): void => {
        if (picked === null) {
          return; // 用户取消选择
        }
        if (!picked.name.toLowerCase().endsWith('.zip')) {
          this.toast(t($r('app.string.module_ext_local_zip_only')));
          return;
        }
        this.appBusy = true;
        LocalPluginStore.installFromZip(ctx, picked)
          .then((info: LocalPluginInfo): void => {
            this.toast(`${t($r('app.string.module_ext_app_installed'))}：${info.name}`);
            this.loadLocalApps();
          })
          .catch((e: Error): void => {
            this.toast(this.appErrorText(e.message));
          })
          .finally((): void => {
            this.appBusy = false;
          });
      })
      .catch((e: Error): void => {
        this.toast(`${t($r('app.string.module_ext_failed'))}：${e.message}`);
      });
  }

  // 本地安装错误码 → i18n 文案（存储层只抛码，文案收敛在 UI 层）
  private appErrorText(code: string): string {
    if (code === ERR_ZIP) {
      return t($r('app.string.module_ext_app_err_zip'));
    }
    if (code === ERR_ROOT) {
      return t($r('app.string.module_ext_app_err_root'));
    }
    if (code === ERR_ID) {
      return t($r('app.string.module_ext_app_err_id'));
    }
    if (code === ERR_ENTRY) {
      return t($r('app.string.module_ext_app_err_entry'));
    }
    if (code === ERR_ENTRY_MISSING) {
      return t($r('app.string.module_ext_app_err_entry_missing'));
    }
    if (code === ERR_EXISTS) {
      return t($r('app.string.module_ext_app_err_exists'));
    }
    return `${t($r('app.string.module_ext_failed'))}：${code}`;
  }

  // 卸载本地应用：确认 → 移入回收区（不 rm，保留最近 5 份，可重装）
  private confirmUninstallApp(info: LocalPluginInfo): void {
    if (this.appBusy || this.busy) {
      return;
    }
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.module_ext_app_uninstall_confirm')),
      message: `${info.name}：${t($r('app.string.module_ext_app_uninstall_msg'))}`,
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.module_ext_uninstall_action')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.uninstallApp(info);
        }
      }
    });
  }

  private uninstallApp(info: LocalPluginInfo): void {
    if (this.appBusy) {
      return;
    }
    this.appBusy = true;
    try {
      const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
      LocalPluginStore.remove(ctx, info.id);
      this.toast(t($r('app.string.module_ext_app_uninstalled')));
      this.loadLocalApps();
    } catch (e) {
      this.toast(`${t($r('app.string.module_ext_failed'))}：${(e as Error).message}`);
    } finally {
      this.appBusy = false;
    }
  }

  // Skill 市场搜索（7378 search：provider_pages 传空、limit 20、lang 跟随内容语言）
  private async search(): Promise<void> {
    const q: string = this.query.trim();
    if (q.length === 0 || this.searching) {
      return;
    }
    this.searching = true;
    try {
      const body: Record<string, Object> = {};
      body['query'] = q;
      const pages: Record<string, Object> = {};
      body['provider_pages'] = pages;
      body['limit'] = 20;
      body['lang'] = 'zh-CN';
      const resp: http.HttpResponse = await this.send('/market/search',
        http.RequestMethod.POST, JSON.stringify(body));
      if (resp.responseCode < 200 || resp.responseCode >= 300) {
        throw new Error(`HTTP ${resp.responseCode}`);
      }
      const data: Record<string, Object> = jsonOf(resp);
      this.results = this.parseMarket(data['results']);
      this.searched = true;
      // 无结果但有 provider 报错时透出原因（对齐 7378：搜索未完成 → 列出错误）
      if (this.results.length === 0) {
        const messages: string = this.marketErrors(data['errors']);
        if (messages.length > 0) {
          this.getUIContext().showAlertDialog({
            title: t($r('app.string.module_ext_search_incomplete')),
            message: messages
          });
        }
      }
    } catch (e) {
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.module_ext_search_failed')),
        message: (e as Error).message
      });
    } finally {
      this.searching = false;
    }
  }

  private parseMarket(value: Object): MarketRow[] {
    const out: MarketRow[] = [];
    if (value === undefined || value === null || !Array.isArray(value)) {
      return out;
    }
    for (const item of value as Object[]) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const row: MarketRow = new MarketRow();
      row.source = typeof r['source'] === 'string' ? r['source'] as string : '';
      row.slug = typeof r['slug'] === 'string' ? r['slug'] as string : '';
      row.name = typeof r['name'] === 'string' ? r['name'] as string : row.slug;
      row.description = typeof r['description'] === 'string' ? r['description'] as string : '';
      row.sourceUrl = typeof r['source_url'] === 'string' ? r['source_url'] as string : '';
      row.version = typeof r['version'] === 'string' ? r['version'] as string : '';
      row.author = typeof r['author'] === 'string' ? r['author'] as string : '';
      if (row.slug.length > 0) {
        out.push(row);
      }
    }
    return out;
  }

  // provider 报错列表 → 换行拼接（对齐 7378：errors.map(e => e.message).join("\n")）
  private marketErrors(value: Object): string {
    if (value === undefined || value === null || !Array.isArray(value)) {
      return '';
    }
    const lines: string[] = [];
    for (const item of value as Object[]) {
      const r: Record<string, Object> = item as Record<string, Object>;
      const msg: string = typeof r['message'] === 'string' ? r['message'] as string : '';
      if (msg.length > 0) {
        lines.push(msg);
      }
    }
    return lines.join('\n');
  }

  private confirmInstallSkill(item: MarketRow): void {
    if (this.installing.length > 0) {
      return;
    }
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.module_ext_install_confirm')),
      message: item.description.length > 0 ? item.description : item.name,
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.module_ext_install_action')),
        action: (): void => {
          this.startInstall(item);
        }
      }
    });
  }

  // 市场安装：POST /skills/hub/install/start → 轮询 /skills/hub/install/status/{task_id}
  private startInstall(item: MarketRow): void {
    this.installing = item.slug;
    const body: Record<string, Object> = {};
    body['bundle_url'] = item.sourceUrl;
    body['version'] = item.version;
    body['enable'] = true;
    this.send('/skills/hub/install/start', http.RequestMethod.POST, JSON.stringify(body))
      .then((resp: http.HttpResponse): void => {
        if (resp.responseCode < 200 || resp.responseCode >= 300) {
          this.finishInstall(`${t($r('app.string.module_ext_failed'))}（HTTP ${resp.responseCode}）`);
          return;
        }
        const data: Record<string, Object> = jsonOf(resp);
        const taskId: string = typeof data['task_id'] === 'string' ? data['task_id'] as string : '';
        if (taskId.length === 0) {
          this.finishInstall(t($r('app.string.module_ext_skill_installed')));
          return;
        }
        this.pollInstall(taskId, 0);
      })
      .catch((e: Error): void => {
        this.finishInstall(`${t($r('app.string.module_ext_failed'))}：${e.message}`);
      });
  }

  private pollInstall(taskId: string, attempt: number): void {
    if (attempt >= POLL_MAX) {
      this.finishInstall(t($r('app.string.module_ext_install_timeout')));
      return;
    }
    this.send(`/skills/hub/install/status/${encodeURIComponent(taskId)}`,
      http.RequestMethod.GET, null)
      .then((resp: http.HttpResponse): void => {
        if (resp.responseCode !== 200) {
          this.schedulePoll(taskId, attempt);
          return;
        }
        const data: Record<string, Object> = jsonOf(resp);
        const status: string = typeof data['status'] === 'string' ? data['status'] as string : '';
        if (status === 'completed' || status === 'success') {
          this.finishInstall(t($r('app.string.module_ext_skill_installed')));
          return;
        }
        if (status === 'failed' || status === 'cancelled') {
          const msg: string = typeof data['error'] === 'string' ? data['error'] as string
            : (typeof data['message'] === 'string' ? data['message'] as string
              : t($r('app.string.module_ext_failed')));
          this.finishInstall(msg);
          return;
        }
        this.schedulePoll(taskId, attempt);
      })
      .catch((): void => {
        this.schedulePoll(taskId, attempt);
      });
  }

  private schedulePoll(taskId: string, attempt: number): void {
    setTimeout((): void => {
      this.pollInstall(taskId, attempt + 1);
    }, POLL_INTERVAL_MS);
  }

  private finishInstall(message: string): void {
    this.installing = '';
    this.toast(message);
  }

  private marketSubtitle(item: MarketRow): string {
    if (item.description.length > 0) {
      return item.description;
    }
    const author: string = item.author.length > 0 ? item.author : t($r('app.string.module_ext_unknown_author'));
    return item.source.length > 0 ? `${item.source} · ${author}` : author;
  }

  build() {
    Column() {
      if (this.error.length > 0) {
        ModuleError(this.error, (): void => {
          this.load();
        })
      } else if (!this.loaded) {
        ModuleLoading(t($r('app.string.module_loading')))
      } else if (this.localMode) {
        this.localContent()
      } else {
        IosGroup({ title: t($r('app.string.module_ext_market')) }) {
          this.searchRow()
          ForEach(this.results, (item: MarketRow) => {
            IosRow({
              icon: $r('app.media.arrow_down_to_line'),
              label: item.name,
              subtitle: this.marketSubtitle(item),
              trailing: this.installing === item.slug
                ? t($r('app.string.module_ext_install_running'))
                : t($r('app.string.module_ext_install_action')),
              tappable: this.installing.length === 0,
              onPress: (): void => {
                this.confirmInstallSkill(item);
              }
            })
          }, (item: MarketRow) => `${item.source}:${item.slug}`)
          if (this.searched && this.results.length === 0) {
            ModuleEmpty($r('sys.symbol.magnifyingglass'),
              t($r('app.string.module_ext_search_empty')),
              t($r('app.string.module_ext_search_empty_hint')),
              true)
          }
        }

        IosGroup({ title: `${t($r('app.string.module_ext_group_apps'))} · ${this.apps.length}` }) {
          ForEach(this.apps, (row: AppRow) => {
            IosRow({
              icon: $r('app.media.layout_grid'),
              label: row.name,
              subtitle: row.description.length > 0 ? row.description
                : `${row.version}${row.status.length > 0 ? ' · ' + row.status : ''}`,
              trailing: t($r('app.string.module_ext_open')),
              tappable: true,
              // 打开该 App 的页面（对齐 7378：App Center 行 → pawapp/[id] 内嵌 Web）。
              // 本组件拿不到导航栈，交事件总线转给根页面 Index 去 pushPath。
              // 带上 entry_page（插件自声明入口）与显示名，详情页按 entry_page 打开 Web。
              onPress: (): void => {
                requestPawApp(row.id, row.entryPage, row.name);
              }
            })
          }, (row: AppRow) => row.id)
        }
        if (this.appsOk && this.apps.length === 0) {
          ModuleEmpty($r('app.media.layout_grid'),
            t($r('app.string.module_ext_apps_empty_title')),
            t($r('app.string.module_ext_apps_empty_subtitle')))
        }

        // 本地插件 = 安装动作（设备 ZIP / URL 安装）；远端 PawApp 与已安装扩展各归其组
        IosGroup({ title: t($r('app.string.module_ext_local_group')) }) {
          IosRow({
            icon: $r('app.media.puzzle'),
            label: t($r('app.string.module_ext_local_zip')),
            subtitle: t($r('app.string.module_ext_local_zip_hint')),
            trailing: this.localInstalling
              ? t($r('app.string.module_ext_install_running'))
              : t($r('app.string.module_ext_local_install')),
            tappable: !this.localInstalling && !this.busy,
            onPress: (): void => {
              this.installLocalZip();
            }
          })
          IosRow({
            icon: $r('app.media.arrow_down_to_line'),
            label: t($r('app.string.module_ext_install_url')),
            subtitle: t($r('app.string.module_ext_install_hint')),
            tappable: this.pluginsOk && !this.busy,
            onPress: (): void => {
              this.openInstall();
            }
          })
        }

        // 本地应用 = 设备安装的插件（离线运行，与远端连接状态无关；两形态共用）
        this.localAppsGroup()

        // 已安装扩展 = 服务端 /plugins 全量（本地插件上传安装成功后的条目也在这里管理与卸载）
        IosGroup({ title: `${t($r('app.string.module_ext_group_plugins'))} · ${this.plugins.length}` }) {
          ForEach(this.plugins, (row: PluginRow) => {
            IosRow({
              icon: row.isApp ? $r('app.media.layout_grid') : $r('app.media.puzzle'),
              label: row.name,
              subtitle: row.version.length > 0
                ? `${row.pluginType} · ${row.version}` : row.description,
              trailing: row.loaded
                ? t($r('app.string.module_ext_running'))
                : t($r('app.string.module_ext_unloaded')),
              tappable: !this.busy,
              onPress: (): void => {
                this.confirmUninstall(row);
              }
            })
          }, (row: PluginRow) => row.id)
        }
        if (this.pluginsOk && this.plugins.length === 0 && this.apps.length === 0) {
          ModuleEmpty($r('app.media.puzzle'),
            t($r('app.string.module_ext_empty_title')),
            t($r('app.string.module_ext_empty_subtitle')))
        }
        // 通知接入：应用内通知是客户端设置，连接与本地形态共用
        this.notifyGroup()
        ModuleFooter(t($r('app.string.module_ext_footer')))
      }
    }
    .width('100%')
    .bindSheet(this.sheetShown, this.sheetContent(),
      moduleSheetOptions(520, this.gate,
        (v: boolean): void => {
          this.sheetShown = v;
        }))
  }

  // 市场搜索行（与 IosRow 同底色/同高，右侧「搜索」动作）
  @Builder
  searchRow() {
    Column() {
      Row({ space: 8 }) {
        // 放大镜按口径用鸿蒙图标（sys.symbol）
        SymbolGlyph($r('sys.symbol.magnifyingglass'))
          .fontSize(17)
          .fontColor([$r('app.color.text_tertiary')])
        TextInput({ placeholder: $r('app.string.module_ext_search_placeholder'), text: $$this.query })
          .fontSize(UiTokens.fsBody)
          .caretColor(this.accent())
          .backgroundColor(Color.Transparent)
          .fontColor($r('app.color.input_text'))
          .placeholderColor($r('app.color.placeholder'))
          .placeholderFont({ size: UiTokens.fsBody })
          .height(38)
          .layoutWeight(1)
          .enterKeyType(EnterKeyType.Search)
          .onSubmit((): void => {
            this.search();
          })
        Text(this.searching
          ? $r('app.string.module_ext_searching') : $r('app.string.module_ext_search'))
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.query.trim().length > 0
            ? this.accent() : $r('app.color.text_tertiary'))
          .onClick((): void => {
            this.search();
          })
      }
      .width('100%')
      .constraintSize({ minHeight: 60 })
      .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad, top: 10, bottom: 10 })
      .alignItems(VerticalAlign.Center)
      .backgroundColor($r('app.color.card_surface'))
      Divider()
        .color($r('app.color.line'))
        .strokeWidth(0.5)
    }
    .width('100%')
  }

  // 打开远端 PawApp 详情面板（复用安装面板的同一张半模态与闸门）
  private openLocalDetail(entry: RemotePawAppEntry): void {
    this.localDetail = entry;
    this.sheetMode = MODE_LOCAL;
    if (this.gate.request()) {
      this.sheetShown = true;
    }
  }

  // 源码仓库交系统浏览器打开（应用内不内嵌浏览器；与社区页链接同一取向）
  private openRepoLink(entry: RemotePawAppEntry): void {
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      ctx.openLink(entry.repoUrl, {}, (err: BusinessError): void => {
        if (err) {
          this.toast(t($r('app.string.module_ext_open_link_failed')));
        }
      });
    } catch (e) {
      this.toast(t($r('app.string.module_ext_open_link_failed')));
    }
  }

  // 本地形态内容：注明卡 + 远端 PawApp 注册表 + 通知接入（无任何网络请求）
  @Builder
  localContent() {
    Column() {
      Text(t($r('app.string.module_ext_local_note_title')))
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.text_primary_strong'))
      Text(t($r('app.string.module_ext_local_note')))
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_secondary'))
        .margin({ top: 6 })
        .width('100%')
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .backgroundColor($r('app.color.card_surface'))
    .borderRadius(UiTokens.cardRadius)

    IosGroup({ title: `${t($r('app.string.module_ext_remote_app_group'))} · ${REMOTE_PAWAPPS.length}` }) {
      ForEach(REMOTE_PAWAPPS, (entry: RemotePawAppEntry) => {
        IosRow({
          icon: $r('app.media.puzzle'),
          label: t(entry.nameResource),
          subtitle: `${t($r('app.string.module_ext_local_frontend'))} · ${entry.version}`,
          trailing: t($r('app.string.module_ext_local_detail')),
          tappable: true,
          onPress: (): void => {
            this.openLocalDetail(entry);
          }
        })
      }, (entry: RemotePawAppEntry) => entry.id)
    }

    // 本地应用：离线运行与远端连接状态无关（安装 / 运行 / 卸载均为本地文件操作）
    this.localAppsGroup()

    this.notifyGroup()

    ModuleFooter(t($r('app.string.module_ext_local_footer')))
  }

  // 本地应用组：设备安装的插件（离线运行；连接与本地形态共用同一组）
  @Builder
  localAppsGroup() {
    IosGroup({ title: `${t($r('app.string.module_ext_app_group'))} · ${this.localApps.length}` }) {
      ForEach(this.localApps, (info: LocalPluginInfo) => {
        // IosRow 只承载单动作，双动作行（运行 / 卸载）自绘（与 IosRow 同几何）
        LocalAppRow({
          label: info.name,
          subtitle: info.version.length > 0 ? `v${info.version}` : '',
          onRun: (): void => {
            this.runLocalApp(info);
          },
          onUninstall: (): void => {
            this.confirmUninstallApp(info);
          }
        })
      }, (info: LocalPluginInfo) => info.id)
      IosRow({
        icon: $r('app.media.puzzle'),
        label: t($r('app.string.module_ext_app_install')),
        subtitle: t($r('app.string.module_ext_app_install_hint')),
        trailing: this.appBusy ? t($r('app.string.module_ext_install_running')) : '',
        tappable: !this.appBusy && !this.busy,
        onPress: (): void => {
          this.installAppZip();
        }
      })
    }
    if (this.localApps.length === 0) {
      ModuleEmpty($r('app.media.layout_grid'),
        t($r('app.string.module_ext_app_empty_title')),
        t($r('app.string.module_ext_app_empty_subtitle')))
    }
  }

  // 通知接入组：连接与本地形态共用（应用内通知是客户端设置，与远端连接状态无关）
  @Builder
  notifyGroup() {
    IosGroup({ title: t($r('app.string.module_ext_notify_group')) }) {
      IosRow({
        icon: $r('sys.symbol.bell'),
        label: t($r('app.string.module_ext_notify_title')),
        subtitle: t($r('app.string.module_ext_notify_subtitle')),
        tappable: true,
        onPress: (): void => {
          // 通知设置页是根页承载的路由：本组件拿不到导航栈，交事件总线转给 Index pushRoute
          requestNotifications();
        }
      })
    }
  }

  // 远端 PawApp 详情面板（MODE_LOCAL）：描述 + 前端扩展标签 + 本地边界说明 + 远端启用指引 + 源码入口
  @Builder
  localDetailSheet() {
    if (this.localDetail !== null) {
      Column() {
        Text(t(this.localDetail.nameResource))
          .fontSize(18)
          .fontWeight(FontWeight.Bold)
          .fontColor($r('app.color.text_primary_strong'))
        Row() {
          Text(`${t($r('app.string.module_ext_local_frontend'))} · ${this.localDetail.version}`)
            .fontSize(UiTokens.fsCaption)
            .fontColor(this.accent())
            .padding({ left: 8, right: 8, top: 3, bottom: 3 })
            .borderRadius(UiTokens.chipRadius)
            .backgroundColor($r('app.color.card_glass'))
        }
        .margin({ top: 8 })
        .alignSelf(ItemAlign.Start)
        Text(t(this.localDetail.descriptionResource))
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 12 })
          .width('100%')
        Text(t(this.localDetail.notesResource))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 10 })
          .width('100%')
        Text(t($r('app.string.module_ext_local_remote_hint')))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 8 })
          .width('100%')
        Button(t($r('app.string.module_ext_local_view_source')))
          .fontSize(UiTokens.fsBody)
          .fontColor(Color.White)
          .backgroundColor(this.accent())
          .borderRadius(12)
          .width('100%')
          .height(44)
          .margin({ top: 20 })
          .onClick((): void => {
            const entry: RemotePawAppEntry | null = this.localDetail;
            if (entry !== null) {
              this.openRepoLink(entry);
            }
            this.closeSheet();
          })
      }
      .width('100%')
      .padding(20)
    }
  }

  @Builder
  sheetContent() {
    Column() {
      if (this.sheetMode === MODE_INSTALL) {
        FieldSheet({
          title: t($r('app.string.module_ext_install')),
          defs: this.installDefs(),
          initial: {} as Record<string, Object>,
          onSave: async (values: Record<string, Object>): Promise<void> => {
            await this.install(values);
          },
          onClose: (): void => {
            this.closeSheet();
          }
        })
      } else if (this.sheetMode === MODE_LOCAL) {
        this.localDetailSheet()
      }
    }
    .width('100%')
    .height('100%')
  }
}

// 本地应用行：双动作（运行 / 卸载）—— IosRow 只承载单 onPress，双动作行在此自绘。
// 与 IosRow 同几何：minHeight 60 / cardPad 内边距 / 30vp 图标底 / 0.5 分隔线；
// 按压反馈 = 底色变化 + 点光源（同 IosRow，不做缩放）。
@Component
struct LocalAppRow {
  label: string = '';
  subtitle: string = '';
  onRun: () => void = (): void => {};
  onUninstall: () => void = (): void => {};
  @State pressed: boolean = false;
  private latch: PressLatch = new PressLatch();
  @StorageLink('appIsDark') dark: boolean = false;

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  build() {
    Column() {
      Row() {
        Stack() {
          Image($r('app.media.layout_grid'))
            .width(18).height(18)
            .fillColor($r('app.color.text_secondary'))
        }
        .width(30)
        .height(30)
        .borderRadius(10)
        .backgroundColor($r('app.color.card_bg'))
        .margin({ right: 12 })
        Column() {
          Text(this.label)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
            .fontColor($r('app.color.text_primary_strong'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          if (this.subtitle.length > 0) {
            Text(this.subtitle)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 2 })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Text($r('app.string.module_ext_app_run'))
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor(accentColor(this.dark))
          .padding({ left: 10, right: 10, top: 6, bottom: 6 })
          .borderRadius(8)
          .onClick((): void => {
            this.onRun();
          })
        Text($r('app.string.module_ext_app_uninstall'))
          .fontSize(UiTokens.fsSecondary)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.status_error'))
          .padding({ left: 10, right: 10, top: 6, bottom: 6 })
          .borderRadius(8)
          .margin({ left: 12 })
          .onClick((): void => {
            this.onUninstall();
          })
      }
      .width('100%')
      .constraintSize({ minHeight: 60 })
      .padding({ left: UiTokens.cardPad, right: UiTokens.cardPad, top: 10, bottom: 10 })
      .backgroundColor(this.pressed ? $r('app.color.card_bg') : $r('app.color.card_surface'))
      .visualEffect(pressEffect(this.pressed))
      .onTouch((e: TouchEvent): void => {
        pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
          this.pressed = v;
        });
      })
      Divider()
        .color($r('app.color.line'))
        .strokeWidth(0.5)
    }
    .width('100%')
  }
}
