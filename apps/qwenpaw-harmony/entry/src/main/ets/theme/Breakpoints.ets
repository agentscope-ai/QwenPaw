/*
 * 响应式断点（官方口径《最佳实践/多设备界面开发/界面布局响应式变化/页面布局场景》）：
 * 按窗口宽度（vp）分三档 —— sm < 600 ≤ md < 840 ≤ lg。
 *
 * 大屏（平板 / PC）下把「手机里铺满整宽」的内容列约束到 CONTENT_MAX 并居中；
 * 标题栏工具条与主标题按同一偏移右移，与内容列左右对齐（否则大屏上搜索框铺满整屏、
 * 内容列却居中，两套左边界对不上）。列表 / 滚动容器仍保持全宽铺底：标题栏沉浸模糊
 * 需要内容能滚到标题栏之下，窗口两侧也要有页面底色托底。
 *
 * 窗口宽度由页面根节点 onAreaChange 实时读到（跟随窗口缩放，PC 上拖窗口同样生效），
 * 不用 mediaquery —— 同一个盒子既用于内容居中、也用于标题偏移，两边必然对齐。
 */

export const BP_LG: number = 840;

// 大屏内容列最大宽度（vp）：超出即居中，避免卡片/表单被拉到上千 vp 宽
export const CONTENT_MAX: number = 840;

// 内容列限宽值（vp）：未到 lg 档返回 0，调用方据此退回 '100%'
export function clampWidthOf(winW: number): number {
  return winW >= BP_LG ? CONTENT_MAX : 0;
}

// 标题栏 / 工具条右移量（vp）：与内容列的居中量一致，两边左边界重合
export function wideOffsetOf(winW: number): number {
  return winW > CONTENT_MAX ? (winW - CONTENT_MAX) / 2 : 0;
}

// 页面尺寸上报：窗口变化时返回应写入的宽度（未变化则原值返回——赋值同值不触发刷新）
export function areaWidthOf(now: Area, cur: number): number {
  const w: number = typeof now.width === 'number' ? now.width as number : 0;
  return (w > 0 && Math.abs(w - cur) > 0.5) ? w : cur;
}

// 大屏内容列宽度（官方缩进布局）：未到 lg 档退回 '100%'
export function wideClampW(pageW: number): Length {
  return pageW >= BP_LG ? CONTENT_MAX : '100%';
}
