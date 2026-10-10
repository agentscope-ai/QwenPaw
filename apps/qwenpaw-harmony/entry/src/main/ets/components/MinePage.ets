/*
 * 关于与自检 —— 现挂在设置页（SettingsPage）内。
 */

import { runCodecSelfTest, SelfTestResult } from '../services/CodecSelfTest';
import { RELAY_PROTOCOL_VERSION, CONTRACT_VERSION, RELAY_OPERATIONS } from '../services/RelayCodec';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

@Component
export struct MinePage {
  @State results: SelfTestResult[] = [];
  @State summary: string = '';
  @State pressed: boolean = false;
  private latch: PressLatch = new PressLatch();

  build() {
    Column() {
      Text($r('app.string.mine_title'))
        .fontSize(18)
        .fontWeight(FontWeight.Bold)
        .margin({ top: 24, bottom: 12 })

      Column() {
        this.infoRow($r('app.string.mine_protocol'), `v${RELAY_PROTOCOL_VERSION}`)
        this.infoRow($r('app.string.mine_contract'), CONTRACT_VERSION)
        this.infoRow($r('app.string.mine_operations'), `${RELAY_OPERATIONS.length}`)
        this.infoRow($r('app.string.mine_frame'), $r('app.string.mine_frame_value'))
      }
      .width('100%')
      .padding(16)
      .borderRadius(16)
      .backgroundColor($r('app.color.card_bg'))
      .margin({ left: 16, right: 16 })

      Button($r('app.string.mine_run'))
        .margin({ top: 20, left: 16, right: 16 })
        // 玻璃底（内容区材质不生效，官方 FAQ 范围规则）+ 自绘按压弹性/点光源
        .backgroundColor($r('app.color.card_glass'))
        .scale({ x: this.pressed ? PRESS_SCALE : 1, y: this.pressed ? PRESS_SCALE : 1 })
        .stateEffect(false)
        .visualEffect(pressEffect(this.pressed))
        .onTouch((e: TouchEvent): void => {
          pressTouch(this.getUIContext(), e, this.latch, (v: boolean): void => {
            this.pressed = v;
          });
        })
        .onClick(() => {
          const r: SelfTestResult[] = runCodecSelfTest();
          this.results = r;
          const passCount: number = r.filter((x: SelfTestResult) => x.pass).length;
          this.summary = `${passCount}/${r.length}`;
        })

      if (this.results.length > 0) {
        Text(this.summary)
          .fontSize(16)
          .fontWeight(FontWeight.Bold)
          .margin({ top: 16, left: 16, right: 16 })

        Column() {
          ForEach(this.results, (r: SelfTestResult) => {
            Column() {
              Row() {
                Text(r.pass ? 'PASS' : 'FAIL')
                  .fontSize(12)
                  .fontWeight(FontWeight.Bold)
                  .fontColor(r.pass ? $r('app.color.status_success') : $r('app.color.status_error'))
                  .width(44)
                Text(r.name)
                  .fontSize(14)
                  .layoutWeight(1)
              }
              .width('100%')

              if (!r.pass) {
                Text(r.detail)
                  .fontSize(12)
                  .fontColor($r('app.color.status_error'))
                  .margin({ top: 2, left: 44 })
                  .wordBreak(WordBreak.BREAK_ALL)
              }
            }
            .padding({ top: 10, bottom: 10 })
          }, (r: SelfTestResult) => r.name)
        }
        .width('100%')
        .padding({ left: 16, right: 16 })
        .margin({ top: 8 })
        .borderRadius(16)
        .backgroundColor($r('app.color.card_bg'))
      }

      Text($r('app.string.mine_footer'))
        .fontSize(12)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: 24, bottom: 32, left: 16, right: 16 })
        .lineHeight(18)
    }
    .width('100%')
    .padding({ left: 4, right: 4 })
  }

  @Builder
  infoRow(label: Resource, value: ResourceStr) {
    Row() {
      Text(label)
        .fontSize(13)
        .fontColor($r('app.color.text_secondary'))
        .width(110)
      Text(value)
        .fontSize(13)
        .layoutWeight(1)
    }
    .width('100%')
    .padding({ top: 5, bottom: 5 })
  }
}
