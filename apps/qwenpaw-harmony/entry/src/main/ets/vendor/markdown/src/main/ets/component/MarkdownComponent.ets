import { Token, Tokens } from '../core'
import { markdown, MarkdownOptionsClass } from '../Index'
import { BlockQuote } from './BlockQuote'
import { Code } from './Code'
import { Heading } from './Heading'
import { Hr } from './Hr'
import { Inline } from './Inline'
import { Latex } from './Latex'
import { MList } from './MList'
import { Paragraph } from './Paragraph'
import { Table } from './Table'

@ComponentV2
export struct MarkdownComponent {
  @Param @Require tokenList: Token[] = []
  @Param @Require options: MarkdownOptionsClass

  build() {
    // 块容器用 Column 而非 List（官方《List》组件文档"懒加载"节：可滚动组件嵌套同滚动方向且未设主轴
    // 尺寸的 List 时，内层 List 全量加载子组件、懒加载失效——markdown 块流本就不滚动、全量展示，
    // 内层 List 只会徒增每个气泡一份滚动机制（手势/滚动态/边界效果）与嵌套手势冲突面，
    // 聊天列表滚动掉帧的结构性来源之一）。布局口径与原 List 一致：同 space 纵向排布 + 满宽。
    Column({ space: (this.options.lineSpacing ?? 12) as number }) {
      Repeat(this.tokenList)
        // 稳定结构键（类型 + 序号 + 块首原文）：流式期间 content 每帧重解析，token 数量/结构会
        // 抖动（尾段与空白块合并拆分、未闭合围栏的自愈翻转）。Repeat 不设 .key() 时以
        // 下标为键，序号一偏移其后所有块全部销毁重建——整块闪烁的结构性来源。
        // 带上块首原文后，未变化的块键不变、原地更新，只有真正在长的那一块重建。
        .key((t: Token, idx: number): string => `${t.type}:${idx}:${t.raw.slice(0, 40)}`)
        .each((repeatItem) => {
          if (repeatItem.item.type === 'hr') {
            Hr({ options: this.options })
          } else if (repeatItem.item.type === 'heading') {
            Heading({ token: repeatItem.item as Tokens.Heading, options: this.options })
          } else if (repeatItem.item.type === 'space') {
            // 空行分隔 token：块缝统一由 Column 的 space 提供。
            // 此前渲染零高占位节点，会在相邻块之间多占一个缝位、把段缝翻倍
            // （段与段 2×space、标题/代码块相邻 1×space —— 行距"宽窄不一"的结构根因）
          } else if (repeatItem.item.type === 'code') {
            Code({ token: repeatItem.item as Tokens.Code, options: this.options })
          } else if (repeatItem.item.type === 'blockquote') {
            BlockQuote({
              token: repeatItem.item as Tokens.Blockquote, options: this.options
            })
          } else if (repeatItem.item.type === 'paragraph') {
            Paragraph({
              token: repeatItem.item as Tokens.Paragraph, options: this.options
            })
          } else if (repeatItem.item.type === 'list') {
            MList({
              tokens: repeatItem.item as Tokens.List, options: this.options
            })
          } else if (repeatItem.item.type === 'text') {
            Inline({
              token: (repeatItem.item as Tokens.Text).tokens ?? [],
              options: this.options
            })
          } else if (repeatItem.item.type === 'table') {
            Table({
              token: repeatItem.item as Tokens.Table, options: this.options
            })
          } else if (repeatItem.item.type === 'html') {
            // Html({ html: repeatItem.item.text, options: this.options })
          } else if (repeatItem.item.type === 'blockLatex') {
            Latex({ token: repeatItem.item, options: this.options })
          } else {
            (this.options.customBlockBuilder ?? markdown.customBlockBuilder)?.builder(repeatItem.item, this.options)
          }
        })

    }.width('100%')
    // 水平对齐走 Column 专属的 alignItems：官方口径 Column 子组件水平对齐默认
    // HorizontalAlign.Center（通用 .align() 管不到 Column 水平轴），不写时窄块（短段落/
    // 标题/hr）在满宽容器里水平居中。md 正文语义是左对齐
    .alignItems(HorizontalAlign.Start)
  }
}
