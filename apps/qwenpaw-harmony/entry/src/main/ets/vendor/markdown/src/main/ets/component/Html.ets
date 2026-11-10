/**
 * @Author : lcc
 * @CreateData : 2024/7/22
 * @Description:
 */
import { MarkdownTheme } from '../config/MarkdownTheme'

@ComponentV2
export struct Html {
  @Param @Require html: string
  @Param @Require theme: MarkdownTheme

  build() {
    Row() {
      Text(this.html)
      .fontColor(this.theme.html?.fontColor)
      .fontSize(this.theme.html?.fontSize)
      .fontWeight(this.theme.html?.fontWeight)
    }
  }
}