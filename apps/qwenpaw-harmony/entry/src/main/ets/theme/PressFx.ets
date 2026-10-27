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

// 按压视效：按下时自身发出明亮光源照亮相邻受光卡片。
//
// 受光类型按卡片高度分两档（官方《点光源效果》：光源位于**组件正中心**，照亮范围有限）：
//   - 短卡（会话/智能体的 GlassCard）：默认受光 DEFAULT_FEATHERING_BORDER 即可整圈照亮（实测按下时
//     卡外背景 12→42，约 35px 羽化外溢）；
//   - 高卡（社区帖卡 ~360vp）：中心到上下边缘 ~180vp，超出默认羽化范围 → 边缘照亮整块失效
//     （实测卡外背景仍为 12，与静止一致）。改用受光类型 BORDER（沿组件边界直接发光，不受中心距离限制）
//     让整圈边界都亮起来。
// 注：不要用 options 光参里的 height 去"够到"高卡边缘 —— 实测那会在卡的右下角炸出一块纯白（255）光斑。
// 两档预设光源（官方 PointLightSourceType）：
//   - BRIGHT（默认档）：明亮点源、照亮范围大——大卡片/列表行，邻居整圈可见；
//   - SOFT：柔和点源、强度弱范围小。
// 并排小键（帖子 dock / 聊天输入条的 40vp 圆形图标键）**不挂点光源**——预设光参真机实测
// 会在键外留轮廓呈方形的光晕（"圆形外面有个方形"）；小键的按压光由所在栏的栏材质
// lightEffect（主题色点光源，官方口径为"按压、触摸"提供光反馈）承载，键体只保留跟手
// scale 收缩。
export function pressEffect(pressed: boolean, borderLight: boolean = false, soft: boolean = false): VisualEffect {
  return new hdsEffect.HdsEffectBuilder()
    .pointLight({
      sourceType: pressed
        ? (soft ? hdsEffect.PointLightSourceType.SOFT : hdsEffect.PointLightSourceType.BRIGHT)
        : hdsEffect.PointLightSourceType.NONE,
      illuminatedType: borderLight
        ? hdsEffect.PointLightIlluminatedType.BORDER
        : hdsEffect.PointLightIlluminatedType.DEFAULT_FEATHERING_BORDER
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
