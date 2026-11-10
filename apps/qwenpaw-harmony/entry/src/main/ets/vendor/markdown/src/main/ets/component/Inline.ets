/**
 * @Author : lcc
 * @CreateData : 2024/7/4
 * @Description:
 */
import { Token } from '../core'
import { parseInlineToken } from '../core/parseInlineToken'
import { MarkdownOptionsClass } from '../Index'


@ComponentV2
export struct Inline {
  @Param @Require options: MarkdownOptionsClass
  @Param @Require token: Token[]
  inlineTextController = new TextController()

  aboutToAppear(): void {
    this.watchToken()
  }

  @Monitor('options.theme')
  watchTheme() {
    this.watchToken()
  }

  @Monitor('token')
  watchToken() {
    parseInlineToken({
      token: this.token,
      theme: this.options.theme,
      uiContext: this.getUIContext(),
      options: this.options
    }).then((data) => {
      this.inlineTextController.setStyledString(data)
    })

  }

  build() {
    Text(undefined, { controller: this.inlineTextController })
      .fontColor(this.options.theme.fontStyle?.fontColor)
      .fontSize(this.options.theme.fontStyle?.fontSize)
      .fontWeight(this.options.theme.fontStyle?.fontWeight)
      .maxLines(this.options.maxLines)
      .textOverflow({ overflow: TextOverflow.Ellipsis })
      .lineSpacing(this.options.inlineLineSpacing)
      // 行高倍率（CSS line-height 语义）：设了即按 倍率×字号 定行盒高，
      // 并覆盖上面的加性 lineSpacing；未设时保持原加性行为
      .lineHeightMultiple(this.options.lineHeightMultiple)
      // 超长不可断 token（URL/路径/代码串）按字断行，不再整词溢出气泡容器
      // （工程正文 Text 的既有口径，vendor 块此前缺失）
      .wordBreak(WordBreak.BREAK_ALL)
  }
}
