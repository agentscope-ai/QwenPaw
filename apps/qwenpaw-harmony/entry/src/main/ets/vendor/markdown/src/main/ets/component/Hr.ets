import { MarkdownOptionsClass } from '../Index'

@ComponentV2
export struct Hr {
  @Param @Require options: MarkdownOptionsClass
  build() {
    Divider()
      .strokeWidth(this.options.theme.hrStyle?.driveWidth)
      .height(this.options.theme.hrStyle?.driveWidth)
      // console 参照（hr margin 1em 0）：上下各让一个块缝 + Column space 共成 1em 档
      .margin({ top: (this.options.lineSpacing ?? 12) as number, bottom: (this.options.lineSpacing ?? 12) as number })
  }
}