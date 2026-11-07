/**
 * @Author : lcc
 * @CreateData : 2024/7/4
 * @Description:
 */
import { Tokens } from '../core'
import { MarkdownOptionsClass } from '../Index'
import { Inline } from './Inline'

@ComponentV2
export struct Paragraph {
  @Param @Require token: Tokens.Paragraph
  @Param @Require options: MarkdownOptionsClass

  build() {
    Inline({ token: this.token?.tokens, options:this.options })
  }
}