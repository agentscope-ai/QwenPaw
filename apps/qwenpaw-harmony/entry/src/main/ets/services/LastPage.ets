/*
 * 二级页记忆（用户意图）：平板/电脑横屏分栏下，切走页签再切回来时把上次点进去的二级页放回右栏。
 * 没有这层记忆时，换页签会把右栏的详情页一起退掉（见 pages/Index.enterTab），切回来右栏就是空的。
 *
 * 与会话页的「最后打开的会话」（services/LastChat）语义一致，差别只有两点：
 *   ① 只在本次进程内有效 —— 产品口径是「打开过、点过才要记忆，启动不用管」，故用进程内单例、不落盘；
 *   ② 只记「路由名 + 稳定标识」，路由参数由调用方按页面形态重建
 *      （NavPathStack 这类对象不能序列化，且各页参数形态不同）。
 */

export interface LastPage {
  route: string;   // router_map 里的页面名：agent / community-article / module / workbench-category
  key: string;     // 页面的稳定标识：智能体 id / 文章 id / 模块 key
}

// tab = Index 的页签序号：1 智能体 / 2 社区 / 3 工作台
const pages: Map<number, LastPage> = new Map<number, LastPage>();

/** 记下某页签最后打开的二级页（key 为空视为无效，不覆盖已有记忆）。 */
export function rememberPage(tab: number, route: string, key: string): void {
  if (key.length === 0) {
    return;
  }
  pages.set(tab, { route: route, key: key });
}

export function recallPage(tab: number): LastPage | null {
  return pages.has(tab) ? pages.get(tab) as LastPage : null;
}
