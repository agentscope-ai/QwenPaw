/**
 * @Author : lcc
 * @CreateData : 2024/7/5
 * @Description:
 */
import { defaultTheme } from './config/DefaultTheme';
import { MarkdownTheme } from './config/MarkdownTheme';
import { MarkedOptions, Token, TokenizerExtension } from './core';
import { LengthMetrics } from '@kit.ArkUI';
import { InlineParams } from './core/parseInlineToken';

export type OnClick = (url?: string) => void

export interface MarkdownOptions {
  theme?: MarkdownTheme
  darkTheme?: MarkdownTheme
  lineSpace?: number | string
  inlineLineSpace?: LengthMetrics
  // 行高倍率（CSS line-height 语义）：设了即按 倍率×字号 定行盒高，
  // 且覆盖加性的 lineSpacing/inlineLineSpace（lineHeightMultiple 官方语义）
  lineHeightMultiple?: number
  darkMode?: boolean,
  options?: MarkedOptions,
  extensions?: TokenizerExtension[]
  imageClick?: OnClick,
  linkClick?: OnClick,
  customBlockBuilder?: WrappedBuilder<[Token, MarkdownOptionsClass]>
  customInlineBuilder?: (tokenItem: Token, params: InlineParams) => void
  //inline元素中 需要显示的最大行数
  maxLines?: number
}


@ObservedV2
export class MarkdownOptionsClass {
  @Trace
  theme: MarkdownTheme
  @Trace
  lineSpacing?: number | string
  @Trace
  inlineLineSpacing?: LengthMetrics
  // @Trace 必须：Inline/Heading/MList 的 build 直接读此字段（.lineHeightMultiple），
  // 未标 @Trace 则选项更新后子树不重渲染
  @Trace
  lineHeightMultiple?: number
  // @Trace 必须：Inline.build 直接读此字段（.maxLines）。@ObservedV2 下未标 @Trace 的属性
  // 变化不产生观测通知（官方《@Trace：类属性变化观测》），展开/收起只改 maxLines 时
  // 子树不会重渲染，截断会静默失效
  @Trace
  maxLines?: number

  // 交互回调随各 Markdown 组件实例的 options 流转。
  // 此前这些回调挂在模块级 markdown 命名空间上，多个 Markdown 实例（首页/编辑器）
  // 同时存在时会互相覆盖，且闭包持有页面引用导致页面无法被 GC。
  linkClick?: OnClick = undefined
  imageClick?: OnClick = undefined
  customInlineBuilder?: (tokenItem: Token, params: InlineParams) => void = undefined
  customBlockBuilder?: WrappedBuilder<[Token, MarkdownOptionsClass]> = undefined

  constructor(theme?: MarkdownTheme) {
    this.theme = theme ?? defaultTheme
  }
}




export namespace markdown {

  export let registerImageClick: OnClick | undefined = undefined

  export let registerLinkClick: OnClick | undefined = undefined

  // 自定义的block渲染
  export let customBlockBuilder: WrappedBuilder<[Token, MarkdownOptionsClass]> | undefined = undefined

  // 自定义的inline渲染
  export let customInlineBuilder: ((tokenItem: Token, params: InlineParams) => void) | undefined = undefined


}

export { marked } from './core';


