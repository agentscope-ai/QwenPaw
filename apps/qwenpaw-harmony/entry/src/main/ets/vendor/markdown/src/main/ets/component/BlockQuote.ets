import { Tokens } from '../core'
import { MarkdownOptionsClass } from '../Index'
import { MarkdownComponent } from './MarkdownComponent'

/**
 * @Author : lcc
 * @CreateData : 2024/7/5
 * @Description:
 */
@ComponentV2
export struct BlockQuote {
  @Param @Require token: Tokens.Blockquote
  @Param @Require options: MarkdownOptionsClass
  @Local blockHeight: Length = 0

  build() {
    Row() {
      Divider()
        .vertical(true)
        .strokeWidth(this.options.theme.blockQuoteStyle?.driveWidth)
        .height(this.blockHeight)
        .color(this.options.theme.blockQuoteStyle?.driveColor)
      MarkdownComponent({ tokenList: this.token?.tokens, options: this.options })
        .margin({ left: 10, right: 20 })
        .layoutWeight(1)
    }
    .backgroundColor(this.options.theme.blockQuoteStyle?.backgroundColor)
    .borderRadius(this.options.theme.blockQuoteStyle?.borderRadius)
    // console 参照（blockquote margin 1em 0、padding-block 0）：纵向留白不落在
    // 底色 padding 里（底纹贴住行盒），而是上下各让一个块缝 + Column space 共成 1em 档
    .margin({ top: (this.options.lineSpacing ?? 12) as number, bottom: (this.options.lineSpacing ?? 12) as number })
    .onSizeChange((_: SizeOptions, newValue: SizeOptions) => {
      if (newValue.height) {
        this.blockHeight = newValue.height
      }
    })
  }
}