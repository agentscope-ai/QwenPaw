/**
 * @Author : lcc
 * @CreateData : 2024/7/6
 * @Description:
 */
import { Token, Tokens } from '../core'
import { Inline } from './Inline'
import { BlockQuote } from './BlockQuote'
import { Code } from './Code'
import { MarkdownOptionsClass } from '../Index'

@ComponentV2
export struct MList {
  @Param @Require tokens: Tokens.List
  @Param @Require options: MarkdownOptionsClass

  build() {
    Column({ space: this.options.lineSpacing }) {
      ForEach(this.tokens?.items, (item: Tokens.ListItem, index: number) => {
        Row({ space: 8 }) {
          if (this.tokens.ordered) {
            Text(typeof this.tokens.start === 'number' ? `${this.tokens.start + index}.` : '')
              .fontColor(this.options.theme.fontStyle?.fontColor)
              .fontSize(this.options.theme.fontStyle?.fontSize)
              .fontWeight(this.options.theme.fontStyle?.fontWeight)
              .lineSpacing(this.options.inlineLineSpacing)
              // 与正文同倍率行盒，序号与首行对齐口径一致
              .lineHeightMultiple(this.options.lineHeightMultiple)
          } else {
            Circle({ width: 6, height: 6 })
              .margin({ top: this.calcMarginTop(item.text, 6) })
              .foregroundColor(this.options.theme.themeColor)
          }
          Column({ space: this.options.lineSpacing }) {
            ForEach(item.tokens, (itemChild: Token, _: number) => {
              if (itemChild.type === 'list') {
                MList({ tokens: itemChild as Tokens.List, options: this.options })
                  .padding({ left: this.options.theme.listStyle?.marginLeft })
              } else if (itemChild.type === 'space') {
                // 空行分隔 token：与顶层 MarkdownComponent 同口径，不渲染占位、
                // 不占缝位（块缝统一由 Column space 给）
              } else if (itemChild.type === 'code') {
                // 列表项内的代码块：此前落入 else 分支被当作行内内容，
                // code token 无 tokens 字段导致内容丢失/报错
                Code({ token: itemChild as Tokens.Code, options: this.options })
              } else if (itemChild.type === 'blockquote') {
                // 列表项内的引用块
                BlockQuote({ token: itemChild as Tokens.Blockquote, options: this.options })
              } else if (itemChild.type === 'html') {
                // 与顶层 MarkdownComponent 的处理保持一致：HTML 块暂不渲染
              } else {
                // 兜底防 undefined：无 tokens 字段的块级 token 不再传入 Inline
                Inline({ token: itemChild['tokens'] ?? [], options: this.options })
              }
            }, (item: Token) => item.raw)
          }.layoutWeight(1)
          .alignItems(HorizontalAlign.Start)
        }.width('100%')
        .alignItems(VerticalAlign.Top)
      }, (item: Tokens.ListItem) => item.raw)
    }
    // 纵向取内容自然高度：本组件挂在内容定高的气泡容器里（父高由子内容决定）。
    // layoutWeight 在竖向容器里是垂直轴权重——父高依赖子内容、本层高又依赖父容器
    // 剩余空间，构成循环依赖，框架按 0 高度裁决本层：全部列表行塌陷、圆点悬浮并与
    // 后续段落重叠、项内文字不可见。固定高度父容器场景下列表顶对齐，语义不变。
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  private calcMarginTop(tokenText?: string, circleSize?: number): number {
    const circle: number = circleSize ?? 0
    // 行高倍率制（console 参照）：首行行盒高 = 倍率×字号，圆点相对首行行盒垂直居中
    if (this.options.lineHeightMultiple !== undefined) {
      const raw: Length | undefined = this.options.theme.fontStyle?.fontSize
      const font: number = typeof raw === 'number' ? raw : 16
      return (this.options.lineHeightMultiple * font - circle) / 2
    }
    // 加性行距制（未设倍率时的原行为）：量测文本默认行高再加一半加性间距
    if (tokenText) {
      let textHeight: Length | undefined = this.getUIContext().getMeasureUtils().measureTextSize({
        textContent: tokenText,
        constraintWidth: '100%',
        fontSize: this.options.theme.fontStyle?.fontSize,
        maxLines: 1
      }).height

      if (textHeight && typeof textHeight === 'number') {
        try {
          return this.getUIContext().px2vp(textHeight) / 2 - (circleSize ?? 0) / 2 +
            Number.parseInt(this.options.lineSpacing?.toString() ?? '0') / 2
        } catch (_) {
        }
      }
    }
    return 0
  }
}

