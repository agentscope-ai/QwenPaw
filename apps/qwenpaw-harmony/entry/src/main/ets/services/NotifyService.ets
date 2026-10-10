/*
 * 系统通知服务 —— NotificationKit（审批等事件接入系统通知中心）。
 * PUBLISH_NOTIFICATION 为系统基本权限（安装自动授予，module.json5 不可声明）；
 * requestEnableNotification 用于用户曾在设置中关闭本应用通知的场景。
 * 幂等：未授权/发布失败只返回 false，不打断 UI 主流程。
 */

import { common } from '@kit.AbilityKit';
import { notificationManager } from '@kit.NotificationKit';

let nextId: number = 1;

// 申请通知权限（系统弹窗）。已授权时直接 true。
export async function requestNotificationPermission(ctx: common.UIAbilityContext): Promise<boolean> {
  try {
    const enabled: boolean = await notificationManager.isNotificationEnabled();
    if (enabled) {
      return true;
    }
    await notificationManager.requestEnableNotification(ctx);
    return await notificationManager.isNotificationEnabled();
  } catch (e) {
    return false;
  }
}

// 发布普通通知（审批提醒等）。返回是否发布成功。
export async function publishNotice(
  ctx: common.UIAbilityContext, title: string, text: string): Promise<boolean> {
  try {
    const enabled: boolean = await notificationManager.isNotificationEnabled();
    if (!enabled) {
      const granted: boolean = await requestNotificationPermission(ctx);
      if (!granted) {
        return false;
      }
    }
    nextId = (nextId % 100000) + 1;
    const content: notificationManager.NotificationContent = {
      notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
      normal: { title: title, text: text }
    };
    // 不指定 notificationSlotType：首次发布时系统自动创建默认槽
    const req: notificationManager.NotificationRequest = {
      id: nextId,
      content: content
    };
    await notificationManager.publish(req);
    return true;
  } catch (e) {
    return false;
  }
}
