import { Tokens } from '../core'
import { parseInlineToken } from '../core/parseInlineToken'
import { MarkdownOptionsClass } from '../Index'

@ComponentV2
export struct Heading {
  @Param @Require token: Tokens.Heading
  @Param @Require options: MarkdownOptionsClass
  inlineTextController = new TextController()
  inlineTextStyle = new MutableStyledString('')

  aboutToAppear(): void {
    this.watchToken()
  }

  @Monitor('options.theme')
  watchTheme() {
    this.watchToken()
  }

  @Monitor('token')
  watchToken() {
    if (this.token?.tokens) {
      let fontStyle = this.options.theme.headingStyle?.[this.token.depth - 1]!
      parseInlineToken({
        token: this.token?.tokens ?? [],
        uiContext: this.getUIContext(),
        theme: this.options.theme,
        options: this.options
        // fontStyle: this.options.theme.headingStyle?.[this.token.depth]!
      }).then((data) => {
        try {
          let style = data?.getStyles(0, data.getString().length, StyledStringKey.FONT)
          style?.forEach((e) => {
            // e.styledValue['fontColor'] = fontStyle.fontColor
            // e.styledValue['fontSize'] = fontStyle.fontSize
            // e.styledValue['fontWeight'] = fontStyle.fontWeight
            data?.replaceStyle({
              start: e.start,
              length: e.length,
              styledKey: StyledStringKey.FONT,
              styledValue:
              new TextStyle({
                fontWeight: fontStyle.fontWeight,
                fontColor: e.styledValue['fontColor'],
              })
            })
          })

        } catch (error) {
        }
        this.inlineTextController.setStyledString(data)
      })

    }
  }

  build() {
    Text(undefined, { controller: this.inlineTextController })
      .fontColor(this.options.theme.headingStyle?.[(this.token?.depth ?? 1) - 1]?.fontColor)
      .fontSize(this.options.theme.headingStyle?.[(this.token?.depth ?? 1) - 1]?.fontSize)
      .fontWeight(this.options.theme.headingStyle?.[(this.token?.depth ?? 1) - 1]?.fontWeight)
      .lineSpacing(this.options.inlineLineSpacing)
      // 与正文同倍率行盒（console 参照 h 的 line-height 与正文同档），未设时保持原加性行为
      .lineHeightMultiple(this.options.lineHeightMultiple)
  }
}
