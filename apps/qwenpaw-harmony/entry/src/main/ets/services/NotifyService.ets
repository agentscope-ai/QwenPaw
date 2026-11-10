/*
 * 系统通知服务 —— NotificationKit（审批等事件接入系统通知中心）。
 * PUBLISH_NOTIFICATION 为系统基本权限（安装自动授予，module.json5 不可声明）；
 * requestEnableNotification 用于用户曾在设置中关闭本应用通知的场景。
 * 幂等：未授权/发布失败只返回 false，不打断 UI 主流程。
 */

import { common } from '@kit.AbilityKit';
import { notificationManager } from '@kit.NotificationKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN = 0x0000;
let nextId: number = 1;

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

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
        hilog.warn(DOMAIN, 'QpwPawNotify', 'publish skipped: notification disabled & not granted');
        return false;
      }
      // 刚授权时 API 层 isNotificationEnabled 已为 true，但 Ans 服务侧开关要等授权对话框
      // 完全退出后才落定（真机实测：publish 早于对话框进程退出 ~500ms 被拒
      // "notification not allowed"，且 publish() 正常 resolve 不抛错）——等对话框收掉再发布
      await sleep(800);
    }
    nextId = (nextId % 100000) + 1;
    const content: notificationManager.NotificationContent = {
      notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
      normal: { title: title, text: text }
    };
    // 槽位显式取服务提醒（SERVICE_INFORMATION：横幅/锁屏/铃声/角标均 Y）。
    // 不指定时默认 OTHER_TYPES（横幅/锁屏/铃声/角标全 N），通知被折叠进「更多通知」
    // 组且不打扰，不适合审批/任务事件类提醒；官方口径：Request 携带
    // notificationSlotType 字段时，对应渠道不存在系统自动创建。
    const req: notificationManager.NotificationRequest = {
      id: nextId,
      content: content,
      notificationSlotType: notificationManager.SlotType.SERVICE_INFORMATION
    };
    await notificationManager.publish(req);
    hilog.info(DOMAIN, 'QpwPawNotify', 'published id=%{public}d: %{public}s', nextId, title);
    return true;
  } catch (e) {
    // 发布失败不再静默（此前 Web 桥通知缺失无从取证）
    hilog.error(DOMAIN, 'QpwPawNotify', 'publish failed: %{public}s', JSON.stringify(e));
    return false;
  }
}
