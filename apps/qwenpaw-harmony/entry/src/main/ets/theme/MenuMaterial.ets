/*
 * 菜单的系统材质（统一出口）
 *
 * 官方《组件适配沉浸光感》：菜单属弹窗类组件/接口，systemMaterial 在**整个页面**均生效
 * （不像普通组件只限标题栏与 End 位置 TabBar）。故所有 bindMenu / bindContextMenu 统一走这里，
 * 档位取 THIN + interactive（按下有光感反馈）；注意设了 systemMaterial 后不要再设
 * backgroundColor / borderColor / borderWidth / shadow —— 它们会被材质覆盖（官方口径）。
 *
 * 半模态（bindSheet）另有统一出口 components/SheetGate.moduleSheetOptions（ULTRA_THICK 厚档）。
 */
import { uiMaterial } from '@kit.ArkUI';

export function menuMaterial(): uiMaterial.ImmersiveMaterial {
  return new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true
  });
}

export function menuOptions(): MenuOptions {
  return { systemMaterial: menuMaterial() };
}

// 不设 placement / enableArrow：官方《菜单控制》bindContextMenu^8+^ 缺省即"菜单跟随点击位置
// 弹出"；enableArrow=true 且无 placement 时会改为"默认在目标物上方显示"——真机实测菜单远离
// 手指（手指 (1500,500) 弹在 (644,1237)），点"选择文本"点不中，故此处只给材质。
export function contextMenuOptions(): ContextMenuOptions {
  return { systemMaterial: menuMaterial() };
}
