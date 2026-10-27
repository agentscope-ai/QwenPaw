/**
 * @Author : lcc
 * @CreateData : 2024/7/4
 * @Description:
 */
import { Tokens } from '../core'
import { CodeToken, highlightCodeAnalyzer } from '../core/analyzer/HighlightAnalyzer'
import { MarkdownOptionsClass } from '../Index'
import { copyToPasteboard } from '../utils'


@ComponentV2
export struct Code {
  @Param @Require token: Tokens.Code
  @Param @Require options: MarkdownOptionsClass
  private codes: string[] = []
  aboutToAppear() {
    this.codes = this.token?.text.split("\n") ?? []
  }

  // 复制按钮图标色：ic_copy.svg 是填充几何（无 stroke），不显式 fillColor 时默认黑色——
  // 深色模式 / 思考块的深色 code 底上完全看不见（真机报障）。按**生效** code 底色判亮度
  // （options.theme 已由 Markdown.watchOptions 按 darkMode 深度合并为生效主题）：
  // 深底用浅暖灰、浅底用深暖灰；底色无法解析时按浅底处理（保持浅色观感）
  private copyIconColor(): string {
    const bg: ResourceColor | undefined = this.options.theme?.code?.backgroundColor
    let luminance: number = 255
    if (typeof bg === 'string') {
      const hex: string = bg.charAt(0) === '#' ? bg.substring(1) : bg
      if (hex.length >= 6) {
        const r: number = parseInt(hex.substring(0, 2), 16)
        const g: number = parseInt(hex.substring(2, 4), 16)
        const b: number = parseInt(hex.substring(4, 6), 16)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
      }
    } else if (typeof bg === 'number') {
      const r: number = (bg >> 16) & 0xff
      const g: number = (bg >> 8) & 0xff
      const b: number = bg & 0xff
      luminance = 0.299 * r + 0.587 * g + 0.114 * b
    }
    return luminance >= 140 ? '#6B6560' : '#B9B5B0'
  }

  // 代码行高跟随正文行高倍率（console 参照：代码块行高继承块级 line-height）：
  // 行盒 = 倍率×代码字号，与周围文字同一节奏；
  // 此前 25vp 写死，代码块节奏与正文脱钩，正文 13pt / 思考 10pt 下缝档不匹配
  private codeLineHeight(): number {
    const multiple: number = this.options.lineHeightMultiple ?? 1.5
    const raw: Length | undefined = this.options.theme.code?.fontSize
    const fontSize: number = typeof raw === 'number' ? raw : 14
    return Math.round(multiple * fontSize)
  }

  @Builder
  codeLine(code: string) {
    Text() {
      ForEach(highlightCodeAnalyzer(code), (token: CodeToken) => {
        Span(token.text)
          .fontColor(this.options.theme?.code?.fontColor?.[token.type])
          .fontSize(this.options.theme.code?.fontSize)
      })
    }
    .textAlign(TextAlign.Start)
  }

  build() {
    Row() {
      Column() {
        Scroll() {
          Column() {
            ForEach(this.codes, (code: string) => {
              Row() {
                this.codeLine(code)
              }
              .height(this.codeLineHeight())
            })
          }.alignItems(HorizontalAlign.Start)
          .padding({
            top: 15,
            bottom: 15,
            left: 10,
            right: 5
          })
        }
        .scrollable(ScrollDirection.Horizontal)
      }.layoutWeight(1)
      .alignItems(HorizontalAlign.Start)

      Image($r('app.media.ic_copy'))
        .width(20)
        .fillColor(this.copyIconColor())
        .margin({ right: 8, top: 8 })
        .onClick(() => {
          copyToPasteboard(this.token?.text)
        })
    }
    .width('100%')
    .borderRadius(this.options.theme.code?.borderRadius)
    .alignItems(VerticalAlign.Top)
    .backgroundColor(this.options.theme.code?.backgroundColor)
    // 边框只在主题显式声明 borderColor 时画（width 0 时不占布局），深浅底同宽避免切换位移
    .border({
      width: this.options.theme.code?.borderColor ? 1 : 0,
      color: this.options.theme.code?.borderColor
    })
  }
}
