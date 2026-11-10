/*
 * 服务层取串 helper。
 * 组件里可以用 this.getUIContext().getHostContext() 取串，但服务层是自由函数（如 assertOk、
 * 校验函数），拿不到 UIContext；故由 EntryAbility.onCreate 注入一次应用 Context，
 * 之后服务层用 t($r('app.string.x')) / tf($r('app.string.x'), ...args) 取本地化串。
 */

import { common } from '@kit.AbilityKit';

let appCtx: common.Context | null = null;

/** 由 EntryAbility.onCreate 注入（仅一次，进程存活期内有效）。 */
export function initI18n(ctx: common.Context): void {
  appCtx = ctx;
}

/** 取串；未初始化或资源缺失时回空串（调用点均有各自的错误提示兜底）。 */
export function t(res: ResourceStr): string {
  if (typeof res === 'string') {
    return res as string;
  }
  const ctx: common.Context | null = appCtx;
  if (ctx === null) {
    return '';
  }
  try {
    return ctx.resourceManager.getStringSync((res as Resource).id);
  } catch (e) {
    return '';
  }
}

/** 带占位符取串（资源里用 %s / %d）。 */
export function tf(res: Resource, ...args: (string | number)[]): string {
  const ctx: common.Context | null = appCtx;
  if (ctx === null) {
    return '';
  }
  try {
    return ctx.resourceManager.getStringSync(res.id, ...args);
  } catch (e) {
    return '';
  }
}
