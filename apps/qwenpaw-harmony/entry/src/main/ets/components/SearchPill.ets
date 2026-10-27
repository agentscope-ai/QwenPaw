/*
 * 标题栏搜索胶囊 —— 会话 / 智能体 / 工作台三个 tab 的 bottomBuilder 工具条共用内容。
 *
 * 为什么抽成组件：`$$` 双向绑定必须落在**具体状态**上，而三个 tab 各有自己的查询串；
 * 抽组件后用 `@Link` 接父组件状态，一处实现三处复用，避免三份重复的输入框标记。
 * 沉浸光感：胶囊自身挂 ImmersiveMaterial —— 位于标题栏材质作用域内（bottomBuilder）→ 材质生效。
 */

import { uiMaterial } from '@kit.ArkUI';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';

// 搜索胶囊高度（vp）——与标题栏工具条预留高度配套
const SEARCH_PILL_H: number = 44;

@Component
export struct SearchPill {
  // 查询串（父组件持有；@Link 双向同步）
  @Link query: string;
  placeholder: Resource = $r('app.string.agents_search_placeholder');
  inputId: string = '';
  // 深浅色直连共享键（标题栏 bottomBuilder 子树只构建一次，prop 传不进来）→ 变化时重建材质取色
  @Watch('rebuild') @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 手指跟随光 = 主题色：仅主题/深浅变化时重建（避免滚动帧帧重建）
  @State material: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.REGULAR,
    interactive: true,
    lightEffect: { color: ThemeManager.get().snapshot().fingerGlow }
  });
  private listener: ThemeListener | null = null;

  aboutToAppear(): void {
    this.listener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
      this.rebuild();
    };
    ThemeManager.get().subscribe(this.listener);
    this.rebuild();
  }

  aboutToDisappear(): void {
    if (this.listener !== null) {
      ThemeManager.get().unsubscribe(this.listener);
      this.listener = null;
    }
  }

  private rebuild(): void {
    this.material = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.REGULAR,
      interactive: true,
      lightEffect: { color: this.isDark ? this.theme.fingerGlowDark : this.theme.fingerGlow }
    });
  }

  build() {
    Row() {
      TextInput({ placeholder: this.placeholder, text: $$this.query })
        .id(this.inputId)
        .fontSize(14)
        .placeholderFont({ size: 14 })
        .caretColor(this.isDark ? this.theme.accentDark : this.theme.accent)
        .backgroundColor(Color.Transparent)
        .fontColor($r('app.color.input_text'))
        .placeholderColor($r('app.color.placeholder'))
        .layoutWeight(1)
        .margin({ left: 14 })
      if (this.query.length > 0) {
        Image($r('app.media.circle_x'))
          .width(16).height(16)
          .fillColor($r('app.color.text_tertiary'))
          .margin({ left: 8 })
          .onClick((): void => {
            this.query = '';
          })
      }
      // 放大镜按口径用鸿蒙图标（sys.symbol），不走 QwenPaw 的 lucide 件
      SymbolGlyph($r('sys.symbol.magnifyingglass'))
        .fontSize(18)
        .fontColor([$r('app.color.text_secondary')])
    }
    .height(SEARCH_PILL_H)
    .width('100%')
    .borderRadius(SEARCH_PILL_H / 2)
    .alignItems(VerticalAlign.Center)
    .padding({ right: 12 })
    .systemMaterial(this.material)
  }
}
