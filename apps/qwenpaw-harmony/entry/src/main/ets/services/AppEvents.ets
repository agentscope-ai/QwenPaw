/*
 * 应用内深链事件总线（跨组件请求导航 + 连接状态广播）。
 * 场景一：App Center（工作台模块页里的组件）需要打开 pawapp 详情页，但它拿不到导航栈 ——
 * 由本总线把「要打开的 appId」暂存 + 发一条事件，根页面（Index）订阅后用自己的 NavPathStack
 * pushPath。参数用模块级变量传递，避免 emitter 载荷走无类型对象字面量（ArkTS 限制）。
 * 场景二：QwenPaw 服务端（连接）变化要让各处重取数据 —— 事件常量统一放这里，
 * 不让「谁发谁收」散落在各个组件文件里。
 * 场景三：扩展模块页的「本地应用」行请求打开本机安装的插件（离线运行，localpawapp 路由）。
 */
import { emitter } from '@kit.BasicServicesKit';

export const PAWAPP_OPEN_EVENT: string = 'qwenpaw.pawapp.open';
export const LOCAL_PAWAPP_OPEN_EVENT: string = 'qwenpaw.localpawapp.open';
export const NOTIFICATIONS_OPEN_EVENT: string = 'qwenpaw.notifications.open';
// 当前连接（QwenPaw 服务端）变了：新增 / 切换 / 移除后广播。订阅方据此重取按服务端取值的数据
// （工作台与会话页重取连接与列表、根页重取服务端主题色 —— 控制台主色存在服务端）。
export const CONN_CHANGE_EVENT: string = 'qp_conn_change';
// 「连接存储被别处改写」事件：设置页切换/移除/断开/重连后发一条，会话页据此重取当前连接并复核。
// 与 CONN_CHANGE_EVENT 分开，避免会话页自发自收（它自己也会发 CONN_CHANGE_EVENT）造成重连死循环。
export const CONN_STORE_EVENT: string = 'qp_conn_store_change';
// 请求切到某个底部页签：二级页（设置页「当前 Agent」等行）拿不到 HdsTabsController，
// 由根页（Index）订阅后用控制器切页（走与点击页签同一路径：onChange → enterTab）。
export const TAB_SWITCH_EVENT: string = 'qwenpaw.tab.switch';

// pawapp 详情页的路由参数（router_map 里 name = 'pawapp'）
// entryPage = /api/pawapps 的 entry_page（插件自声明入口，如 /plugin/{id}）；
// 为空时页面回退 /apps/{id}（desktop PawApp 宿主路由）
export interface PawAppParam {
  appId: string;
  entryPage: string;
  name: string;
}

// 本地 PawApp 详情页的路由参数（router_map 里 name = 'localpawapp'）：本机安装的前端插件，
// 离线运行（entry 为 plugin.json 的 entry.frontend，相对插件根目录）
export interface LocalPawAppParam {
  id: string;
  name: string;
  entry: string;
}

// 扫码配对页的路由参数（router_map 里 name = 'scan'）：页面需要自己 pop 回跳，故随参数带栈
// （与设置页 param.stack 同一口径）；调用方用 pushPathByName 的 onPop 回调接收配对结果。
export interface ScanRouteParam {
  stack: NavPathStack;
}

// 只带导航栈的通用页面入参（页面自行 pop / push，如平台部署页）
export interface StackOnlyParam {
  stack: NavPathStack;
}

let pendingAppId: string = '';
let pendingAppEntryPage: string = '';
let pendingAppName: string = '';
let pendingTabIndex: number = -1;
let pendingLocalAppId: string = '';
let pendingLocalAppName: string = '';
let pendingLocalAppEntry: string = '';

// 请求切到某个底部页签（0=会话 / 1=智能体 / 2=社区 / 3=工作台）
export function requestTab(index: number): void {
  pendingTabIndex = index;
  emitter.emit(TAB_SWITCH_EVENT);
}

export function takeTabRequest(): number {
  const value: number = pendingTabIndex;
  pendingTabIndex = -1;
  return value;
}

export function requestNotifications(): void {
  emitter.emit(NOTIFICATIONS_OPEN_EVENT);
}

// 连接变化广播（由 ConnectionStore 在新增/切换/移除后调用）
export function notifyConnectionChange(): void {
  emitter.emit(CONN_CHANGE_EVENT);
}

// 「连接存储被改写」广播（由设置页/部署页在切换或断开后调用）
export function notifyConnectionStoreChange(): void {
  emitter.emit(CONN_STORE_EVENT);
}

export function requestPawApp(appId: string, entryPage: string, name: string): void {
  pendingAppId = appId;
  pendingAppEntryPage = entryPage;
  pendingAppName = name;
  emitter.emit(PAWAPP_OPEN_EVENT);
}

export function takePawAppRequest(): PawAppParam {
  const param: PawAppParam = {
    appId: pendingAppId,
    entryPage: pendingAppEntryPage,
    name: pendingAppName
  };
  pendingAppId = '';
  pendingAppEntryPage = '';
  pendingAppName = '';
  return param;
}

// 请求打开本地 PawApp 详情（本机插件离线运行；与 requestPawApp 同模式）
export function requestLocalPawApp(id: string, name: string, entry: string): void {
  pendingLocalAppId = id;
  pendingLocalAppName = name;
  pendingLocalAppEntry = entry;
  emitter.emit(LOCAL_PAWAPP_OPEN_EVENT);
}

export function takeLocalPawAppRequest(): LocalPawAppParam {
  const param: LocalPawAppParam = {
    id: pendingLocalAppId,
    name: pendingLocalAppName,
    entry: pendingLocalAppEntry
  };
  pendingLocalAppId = '';
  pendingLocalAppName = '';
  pendingLocalAppEntry = '';
  return param;
}

// —— 键盘缝检测探针：会话页（ChatDetailPage）页根节点的实测底边（全局 vp）——
// 会话页对键盘用 RESIZE 压缩，页根即被压缩的内容节点；HdsNavigation 外层节点不受影响
// （键盘避让在其内部完成），故缝只能测「内容实际底边」vs「窗口底 − 键盘避让区」。
// HDS 内部键盘 inset 停在旧值时，内容底边偏高 ~44px（输入胶囊被顶高的症状本身）。
// 模块级变量传值（同本文件的 request/take 模式），避免跨 NavDestination 子树绕 emitter。
let seamPageBottomVp: number = -1; // -1 = 会话页不在栈上（探针未挂载）

export function setSeamPageProbe(bottomVp: number): void {
  seamPageBottomVp = bottomVp;
}

export function takeSeamPageProbe(): number {
  return seamPageBottomVp;
}
