/*
 * 半模态开关闸门（bindSheet 专用）—— 只决定「何时开」，不持有业务字段。
 *
 * 为什么需要它：bindSheet 的 isShow 若用 $$ 双向绑定，用户以返回键 / 下拉 / 遮罩关闭面板时，
 * 框架会在**回退动画结束**时把 isShow 写回 false。若紧接着请求打开另一张面板，
 * 这次回写会把新面板关掉 —— 表现为「新弹窗弹一下就退出」
 * （真机日志实证：req-open 之后 286ms 出现一次非本组件发起的 shown=false）。
 *
 * 结构性做法（不靠延时兜底）：
 *   ① isShow 单向传入 bindSheet（框架不再回写组件状态）；
 *   ② 用框架回调维护「回退动画进行中」：onWillDisappear 置位、onDisappear 收尾；
 *      回退动画期间到来的打开请求只登记排队，等 onDisappear 再开；
 *   ③ 排队判据只用框架给的 closing，不依赖组件自己的 isShow 值，
 *      避免自置状态与真实面板不同步时把后续打开永久挡在队列里。
 * 面板内容由组件自己的字段（editor / editingJob 等）承载：请求时先落字段，排队只影响打开时机。
 */

import { uiMaterial } from '@kit.ArkUI';

export class SheetGate {
  private queued: boolean = false;
  private closing: boolean = false;
  private closingAt: number = 0;

  // 回退动画开始：onWillDisappear（框架主导的返回键/下拉/遮罩关闭）与程序化关闭都走这里
  beginClose(): void {
    this.closing = true;
    this.closingAt = Date.now();
  }

  // 请求打开：true = 调用方可立即置 isShow=true；false = 已排队，等 onDisappear 再打开。
  // 宽限期自愈：「回退中」只为了避免在回退动画期间拉起新面板（真机实测框架回写约 286ms 后才到），
  // 而面板回退动画不会超过几百毫秒 —— 超过宽限期仍停在 closing，只可能是"关闭动画结束后又被置位"
  // 的残留（此时排队的打开请求永远等不到 onDisappear），按可开处理，不再把后续打开卡死。
  request(): boolean {
    if (this.closing && Date.now() - this.closingAt < CLOSE_GRACE_MS) {
      this.queued = true;
      return false;
    }
    this.closing = false;
    this.queued = false;
    return true;
  }

  // onDisappear：回退动画结束 → true = 有排队的打开请求（调用方置 isShow=true），false = 复位
  settled(): boolean {
    this.closing = false;
    const q: boolean = this.queued;
    this.queued = false;
    return q;
  }
}

// 回退宽限期（ms）：小于它才认为"回退动画可能还在跑"，超过即视为残留状态
const CLOSE_GRACE_MS: number = 700;

/*
 * 工作台各模块半模态的统一外观与回调（对齐官方示例《半模态设置系统材质》示例 10）：
 *   - systemMaterial：弹窗类取厚档 ImmersiveMaterial(ULTRA_THICK) → 面板自带沉浸光感；
 *   - backgroundColor 必须置透明，否则会把材质自带的背景盖掉；
 *   - 官方口径：设 systemMaterial 后不建议同用 borderWidth / borderColor / shadow。
 * 同时把开关状态同步与排队回调收在一处，各模块只传高度与写状态的闭包。
 *
 * 材质等级无需也无法自设：uiMaterial.MaterialLevel 由设备算力决定（getGlobalMaterialLevel 只读），
 * 低算力设备仅保留一种材质样式、ImmersiveStyle 不生效 —— 即 uiMaterial 天然自适应系统沉浸光感等级。
 * 但设备完全不支持沉浸式材质时材质无效，此时若底色仍为透明，面板会整块透明不可用 → 退回实底。
 */
const IMMERSIVE_SUPPORTED: boolean = uiMaterial.isImmersiveMaterialSupported();

// preferCenter：宽屏（平板/PC 横屏）用居中形态 —— 官方 preferType 口径：半模态在不同宽度设备上
// 形态能力不同；底部形态在宽屏上会铺满整屏，既没有"窗外"可点，也不像弹窗
export function moduleSheetOptions(height: SheetSize | Length, gate: SheetGate,
  setShown: (shown: boolean) => void, preferCenter: boolean = false): SheetOptions {
  const material: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.ULTRA_THICK
  });
  const options: SheetOptions = {
    height: height,
    preferType: preferCenter ? SheetType.CENTER : SheetType.BOTTOM,
    dragBar: true,
    showClose: true,
    backgroundColor: IMMERSIVE_SUPPORTED ? Color.Transparent : $r('app.color.page_bg'),
    systemMaterial: IMMERSIVE_SUPPORTED ? material : undefined,
    // 框架开始回退（返回键 / 下拉 / 遮罩）→ 标记回退中，并把状态落到 false：
    // 状态与真实面板一致，排队打开时才会有真实的 false→true 边沿（否则框架不会重新拉起面板）
    onWillDisappear: (): void => {
      gate.beginClose();
      setShown(false);
    },
    // 回退动画结束：有排队的打开请求就在此刻打开（此时是真实的 0→1 边沿）
    onDisappear: (): void => {
      if (gate.settled()) {
        setShown(true);
      }
    }
  };
  return options;
}
