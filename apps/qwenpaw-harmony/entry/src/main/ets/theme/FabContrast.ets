// 沉浸光感悬浮按钮（社区「回到顶部」×2 / 聊天「回到底部」）字体对比度采样
//
// 按钮浮在滚动内容之上，固定字色会随底下内容明暗撞色（深底上深色字看不见）。
// 官方路径：uiContext.getComponentSnapshot().get(id) 取宿主组件最近一帧绘制 →
// PixelMap.readPixelsToArea 只读按钮所在的小区域（BGRA_8888）→ 平均亮度判深浅 →
// 调用方翻转布尔，按钮既有的 .animation(200ms) 负责字色插值过渡。
//
// 采样时机由调用方控制：只在滚动停稳（onScrollStop）/ 内容更新 / 主题切换后触发，
// 且带去抖与在途守卫 —— 不逐帧采样，不打扰滚动流畅性。
// 任何失败（组件离屏 / 读像素失败 / 区域无有效像素）一律返回 null：调用方保持当前色。
import { image } from '@kit.ImageKit';
import { UIContext } from '@kit.ArkUI';

// 采样区域（vp，相对截图宿主组件左上角）
export interface FabSampleRegionVp {
  x: number;
  y: number;
  w: number;
  h: number;
}

// 平均感知亮度（Rec.601）低于此值 = 深色底 → 按钮用浅色字
const LUMA_DARK_THRESHOLD: number = 0.52;
// 截图缩放：亮度判定不需要全分辨率，0.5 把位图压到 1/4（区域换算按实际尺寸自校准）
const SNAPSHOT_SCALE: number = 0.5;
// 区域内不透明像素少于此数 = 判定无依据（例如磨砂背板淡出后的全透明区）
const MIN_OPAQUE_PIXELS: number = 16;

/**
 * 采样宿主组件某区域的平均亮度，判定按钮底下是否为深色内容。
 *
 * @param uiContext 当前 UI 上下文
 * @param hostId    截图目标组件的 .id()（按钮与滚动内容的共同宿主，全屏 Stack）
 * @param regionVp  按钮附近采样区域（vp，宿主坐标系）
 * @param hostWVp   宿主当前宽（vp，onAreaChange 实测）
 * @param hostHVp   宿主当前高（vp，onAreaChange 实测）
 * @returns true = 深色底（用浅色字） / false = 浅色底（用深色字） / null = 采样失败（保持现状）
 */
export function sampleFabBackdropIsDark(uiContext: UIContext, hostId: string,
  regionVp: FabSampleRegionVp, hostWVp: number, hostHVp: number): Promise<boolean | null> {
  if (hostWVp <= 0 || hostHVp <= 0 || regionVp.w <= 0 || regionVp.h <= 0) {
    return Promise.resolve<boolean | null>(null);
  }
  return uiContext.getComponentSnapshot().get(hostId, {
    scale: SNAPSHOT_SCALE,
    waitUntilRenderFinished: true
  }).then((pm: image.PixelMap): Promise<boolean | null> => {
    return readRegionLuma(pm, regionVp, hostWVp, hostHVp)
      .catch((): boolean | null => {
        return null;
      })
      .then((dark: boolean | null): boolean | null => {
        pm.release();
        return dark;
      });
  }).catch((): boolean | null => {
    // 组件离屏 / 截图失败：不阻塞 UI，保持当前字色
    return null;
  });
}

// 读小区域 BGRA 像素 → 平均感知亮度 → 深浅判定
function readRegionLuma(pm: image.PixelMap, regionVp: FabSampleRegionVp,
  hostWVp: number, hostHVp: number): Promise<boolean | null> {
  const info: image.ImageInfo = pm.getImageInfoSync();
  const pmW: number = info.size.width;
  const pmH: number = info.size.height;
  if (pmW <= 0 || pmH <= 0) {
    return Promise.resolve<boolean | null>(null);
  }
  // vp → px 按实际截图尺寸自校准（对系统显示缩放 / 截图 scale 均稳健，不依赖 display.density）
  const kx: number = pmW / hostWVp;
  const ky: number = pmH / hostHVp;
  const x: number = Math.max(0, Math.min(pmW - 1, Math.round(regionVp.x * kx)));
  const y: number = Math.max(0, Math.min(pmH - 1, Math.round(regionVp.y * ky)));
  const w: number = Math.max(1, Math.min(Math.round(regionVp.w * kx), pmW - x));
  const h: number = Math.max(1, Math.min(Math.round(regionVp.h * ky), pmH - y));
  const area: image.PositionArea = {
    pixels: new ArrayBuffer(w * h * 4),
    offset: 0,
    stride: w * 4,
    region: { x: x, y: y, size: { width: w, height: h } }
  };
  return pm.readPixelsToArea(area).then((): boolean | null => {
    const bytes: Uint8Array = new Uint8Array(area.pixels);
    let sum: number = 0;
    let n: number = 0;
    for (let i = 0; i < bytes.length; i += 4) {
      // BGRA：跳过透明像素（隐藏态按钮 / 磨砂背板淡出区不参与判定）
      if (bytes[i + 3] < 128) {
        continue;
      }
      sum += (0.114 * bytes[i] + 0.587 * bytes[i + 1] + 0.299 * bytes[i + 2]) / 255;
      n++;
    }
    if (n < MIN_OPAQUE_PIXELS) {
      return null;
    }
    return sum / n < LUMA_DARK_THRESHOLD;
  });
}
