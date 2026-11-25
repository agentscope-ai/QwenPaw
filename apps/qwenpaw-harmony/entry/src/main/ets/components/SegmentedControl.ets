/*
 * 连排分段按钮（两段）：一个大框 + 框内滑块跟手滑过去 + 沉浸材质。
 *
 * 三条依据（都踩过坑，别再各自实现）：
 *   - 框（材质）：内容区要让沉浸材质真生效，只有 `Toggle(ToggleType.Button)` 外壳这一条路
 *     —— 官方《沉浸光感常见问题》的豁免名单 = 弹窗类 / Slider / Toggle / Select（其余组件仅在
 *     Navigation 标题栏或 barPosition=End 的底部 TabBar 内生效）。外壳透明底 + selectedColor 透明，
 *     只借它的材质与交互形变；框内两段各自处理点击。
 *   - 滑块底色：纯浅色玻璃 `card_glass`。主题色玻璃叠主题色带 Δ≈6/255、浅色玻璃再挂材质 Δ≈8/255
 *     都读不出来，纯浅色玻璃 Δ≈40/255 才看得出"跑过去"（真机三次取样结论）。
 *   - 跟手：官方配方（FAQ faqs-arkui-577）——`PanGesture` 的 `onActionUpdate` 里按 `event.offsetX`
 *     更新 `translate`，`onActionEnd` 落位；官方示例取 `distance: 1`，让手势立即识别（默认 5vp 起判，
 *     前 5vp 不动 → 观感"不跟手"）。落位判定用**滑块最终位置过半**，不用滑动方向 —— 方向判定与手指
 *     位移容易反（左滑到底该切到哪一段取决于滑块在左还是右）。
 *
 * 用法：`selectedIndex`（0=左 / 1=右，@Prop + @Watch 双向同步），`onChange(index)` 点/拖都走它。
 */
import { uiMaterial } from '@kit.ArkUI';

@Component
export struct SegmentedControl {
  labels: Resource[] = [];
  @Prop @Watch('syncPill') selectedIndex: number = 0;
  // 段高（不能叫 height —— 与 CustomComponent 基类属性同名会报类型冲突）
  segHeight: number = 26;
  pad: number = 3;
  material: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  onChange: (index: number) => void = (index: number): void => {};
  // 滑块位移（vp）：静止 = 0 或半宽；拖动中 = 跟手。框内宽度由 onAreaChange 实测（支持任意宽度）
  @State pillX: number = 0;
  @State innerW: number = 0;
  private dragBase: number = 0;

  private maxX(): number {
    return this.innerW > 0 ? this.innerW / 2 : 0;
  }

  // 选中项变化（外部或内部）→ 滑块补间跑到对应半边
  syncPill(): void {
    const target: number = this.selectedIndex === 1 ? this.maxX() : 0;
    if (this.pillX === target) {
      return;
    }
    this.getUIContext().animateTo({ duration: 220, curve: Curve.EaseOut }, (): void => {
      this.pillX = target;
    });
  }

  private pick(index: number): void {
    if (index === this.selectedIndex) {
      return;
    }
    // 先让滑块补间到位，再报选中变化（父组件改 selectedIndex 后 @Watch 会再同步一次，幂等）
    this.getUIContext().animateTo({ duration: 220, curve: Curve.EaseOut }, (): void => {
      this.pillX = index === 1 ? this.maxX() : 0;
    });
    this.onChange(index);
  }

  build() {
    Toggle({ type: ToggleType.Button, isOn: false }) {
      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width('50%')
          .height(this.segHeight)
          .borderRadius(this.segHeight / 2)
          .backgroundColor($r('app.color.card_glass'))
          .translate({ x: this.pillX })
        Row() {
          this.segment(0)
          this.segment(1)
        }
        .width('100%')
        .height(this.segHeight)
      }
      .width('100%')
      .height(this.segHeight)
      .onAreaChange((_old: Area, now: Area): void => {
        const w: number = Number(now.width) as number;
        if (w <= 0 || this.innerW === w) {
          return;
        }
        this.innerW = w;
        // 首次量到宽度：把滑块直接就位（不走进场动画）
        this.pillX = this.selectedIndex === 1 ? w / 2 : 0;
      })
    }
    .width('100%')
    .padding(this.pad)
    .borderRadius((this.segHeight + this.pad * 2) / 2)
    // 透明底：玻璃观感由沉浸材质给（官方按钮示例即「透明底 + ImmersiveMaterial」）
    .backgroundColor(Color.Transparent)
    .systemMaterial(this.material)
    // Toggle 每次点按都会翻转自身开关态 → 抹掉选中底色，选中态只由框内滑块表达
    .selectedColor(Color.Transparent)
    .onChange((isOn: boolean): void => {
      // 外壳只承载材质/形变；点/拖由框内两段与手势决定
    })
    // 跟手拖动：distance 1 立即识别；拖动中滑块跟手指，离手按「过半」落位
    .gesture(
      PanGesture({ direction: PanDirection.Horizontal, distance: 1 })
        .onActionStart((): void => {
          this.dragBase = this.pillX;
        })
        .onActionUpdate((event: GestureEvent): void => {
          const next: number = this.dragBase + (event.offsetX as number);
          this.pillX = next < 0 ? 0 : (next > this.maxX() ? this.maxX() : next);
        })
        .onActionEnd((event: GestureEvent): void => {
          const landed: boolean = (this.dragBase + (event.offsetX as number)) > this.maxX() / 2;
          this.pick(landed ? 1 : 0);
        })
    )
  }

  @Builder
  segment(index: number) {
    Text(this.labels.length > index ? this.labels[index] : $r('app.string.tab_chats'))
      .fontSize(14)
      .fontWeight(this.selectedIndex === index ? FontWeight.Medium : FontWeight.Normal)
      // 未选中也用正文主色（深色=白、浅色=深），只靠字重与滑块区分选中态：
      // 未选中用 text_tertiary 在深色下是灰字，与浅色玻璃滑块混在一起读不出来。
      .fontColor($r('app.color.text_primary_strong'))
      .textAlign(TextAlign.Center)
      .width('50%')
      .height(this.segHeight)
      .onClick((): void => {
        this.pick(index);
      })
  }
}
