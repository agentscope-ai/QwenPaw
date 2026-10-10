/*
 * 按压反馈（对齐官方《空间化 · 沉浸光感》两项能力）
 *   按压弹性反馈：按下即刻收缩（跟手），抬手弹性回弹（像真的被按下）；
 *   按压点光源  ：hdsEffect.pointLight —— 按下时组件自身发光，照亮相邻的受光卡片。
 *
 * 官方《点光源效果》要点（决定下面的写法）：
 *   - 支持组件：Button / Toggle / Row / Column / Image / Flex / Stack / Select / Menu / MenuItem（正文内容流可用）；
 *   - 受光组件若设置了 border 的颜色或宽度，会覆盖点光源效果 → 可按压卡片一律不加 border，圆角只由 borderRadius 给；
 *   - 光源位置初始化为组件中心且不随位移更新 → 只在按压期间发光（不在滚动中长亮）；
 *   - 单个组件最多同时受 12 个光源照亮；
 *   - 组件自身按压时不再叠加 pressShadow（其径向白光会把整卡刷白），只保留点光源照亮邻居。
 */
import { hdsEffect } from '@kit.UIDesignKit';
import { curves } from '@kit.ArkUI';

// 按下收缩比（缩放中心 = 组件中心）
export const PRESS_SCALE: number = 0.96;

// 按下收缩时长：必须足够短，否则轻点（手指 100ms 内抬起）等不到形变就回弹，表现为"按不出来"
const PRESS_IN_MS: number = 90;
// 按压最小驻留时长：轻点也保证完整走完「按下 → 回弹」，按压反馈一定看得见
const PRESS_MIN_MS: number = 160;

// 按压状态闩：记录本次按下时刻（每个可按压组件各持有一个实例）
export class PressLatch {
  downAt: number = 0;
}

// 按压视效：按下时自身发出明亮光源照亮相邻受光卡片；常态受光（被邻居按压的光源点亮）
export function pressEffect(pressed: boolean): VisualEffect {
  return new hdsEffect.HdsEffectBuilder()
    .pointLight({
      sourceType: pressed ? hdsEffect.PointLightSourceType.BRIGHT : hdsEffect.PointLightSourceType.NONE,
      illuminatedType: hdsEffect.PointLightIlluminatedType.DEFAULT_FEATHERING_BORDER
    })
    .buildEffect();
}

// 触摸处理：按下即时收缩（90ms 摩擦曲线，跟手），抬手弹性回弹（物理弹簧，带轻微回弹）；
// 轻点时抬手早于最小驻留 → 延后到驻留结束再回弹，避免"按得很快看不到反馈"。
export function pressTouch(ui: UIContext, event: TouchEvent, latch: PressLatch,
  apply: (pressed: boolean) => void): void {
  if (event.type === TouchType.Down) {
    latch.downAt = Date.now();
    ui.animateTo({ duration: PRESS_IN_MS, curve: Curve.Friction }, (): void => {
      apply(true);
    });
  } else if (event.type === TouchType.Up || event.type === TouchType.Cancel) {
    const release = (): void => {
      ui.animateTo({ curve: curves.springMotion(0.3, 0.8) }, (): void => {
        apply(false);
      });
    };
    const wait: number = PRESS_MIN_MS - (Date.now() - latch.downAt);
    if (wait > 0) {
      setTimeout(release, wait);
    } else {
      release();
    }
  }
}
