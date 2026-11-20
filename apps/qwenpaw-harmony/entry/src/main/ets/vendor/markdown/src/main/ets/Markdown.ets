import { Token } from './core'
import { MarkdownComponent } from './component/MarkdownComponent'
import { parseMarkdown, parseMarkdownSync, hasFunctionMember } from './utils'
import { MarkdownOptions, MarkdownOptionsClass } from './Index'
import { defaultDarkTheme, defaultTheme } from './config/DefaultTheme'
import { LengthMetrics } from '@kit.ArkUI'
import deepMerge from './merge'
import { taskpool } from '@kit.ArkTS'
import { BusinessError } from '@kit.BasicServicesKit'


@ComponentV2
export struct Markdown {
  /**
   * 外层传入时仅需传递content或token
   */
  @Param token: Token[] = []
  @Param content: string = ''
  @Param options?: MarkdownOptions = undefined
  @Local tokenList: Token[] = []
  @Local optionsClass: MarkdownOptionsClass = new MarkdownOptionsClass()
  @Event onLoading?: () => void
  @Event onSuccess?: () => void
  @Event onError?: (e: BusinessError) => void
  // 解析序号守卫：content 快速连续变更时多个 taskpool 任务并发，
  // 先发起但后返回的旧结果不能覆盖新结果
  private parseSeq: number = 0

  /**
   * 稳定 token 引用（流式渲染防闪结构解）。
   * content 流式期间每次 flush 都整体重解析，解析器每次返回全新 token 对象数组。
   * Repeat 全量加载模式同键节点保留，但框架层每帧用新数组项更新子组件内容；
   * @Param 对对象类型按引用级观测——新引用即视为变化，未变化块的子组件
   * @Monitor('token') 每帧都被触发，逐块重解析重布局，表现为整段"一直在闪"。
   * 解析是纯函数：同位置 type 与 raw 相同则解析结果必相同，复用旧 token 引用，
   * 未变化块 @Param 观测到同一引用 → 不触发 → 零重解析零重布局；
   * 只有真正在长的块拿到新引用。整表完全相同时返回旧数组本身，
   * tokenList 赋值不产生观测变化，Repeat 连 diff 都不做。
   */
  private stableTokenList(data: Token[]): Token[] {
    const old = this.tokenList
    let allSame = old.length === data.length
    const out: Token[] = []
    for (let i = 0; i < data.length; i++) {
      const nt: Token = data[i]
      if (i < old.length) {
        const ot: Token = old[i]
        if (ot.type === nt.type && (ot.raw ?? '') === (nt.raw ?? '')) {
          out.push(ot)
          continue
        }
      }
      allSame = false
      out.push(nt)
    }
    return allSame ? old : out
  }

  aboutToAppear(): void {
    this.watchOptions()
    if (this.content && this.content.trim().length !== 0) {
      this.watchContent()
    } else if (this.token.length != 0) {
      this.watchToken()
    }
  }

  @Monitor('token')
  watchToken() {
    this.tokenList = this.token.length === 0 ? [] : this.stableTokenList(this.token)
  }

  @Monitor('content')
  watchContent() {
    if (this.content && this.content.trim().length !== 0) {
      this.onLoading?.()
      const seq = ++this.parseSeq
      const markedOptions = this.options?.options
      const markedExtensions = this.options?.extensions
      if (hasFunctionMember(markedOptions) || hasFunctionMember(markedExtensions)) {
        // options/extensions 含函数成员（tokenizer/hooks 等无法跨线程序列化），
        // 回退主线程同步解析，避免 taskpool.execute 抛运行时错误
        try {
          this.tokenList = this.stableTokenList(parseMarkdownSync(this.content, markedOptions, markedExtensions))
          this.onSuccess?.()
        } catch (e) {
          this.onError?.(e as BusinessError)
        }
      } else {
        taskpool.execute(parseMarkdown, this.content, markedOptions, markedExtensions).then((data) => {
          if (seq !== this.parseSeq) {
            return // 已有更新的 content 发起解析，丢弃本次旧结果
          }
          this.tokenList = this.stableTokenList(data as Token[])
          this.onSuccess?.()
        }).catch((e: BusinessError) => {
          if (seq === this.parseSeq) {
            this.onError?.(e)
          }
        })
      }
    } else {
      // content 置空时清理渲染，避免预览区残留上一个文档
      this.parseSeq++
      this.tokenList = []
    }
  }

  @Monitor('options')
  watchOptions() {
    if (this.options) {
      this.optionsClass.theme = this.options.darkMode ? deepMerge(defaultDarkTheme, this.options.darkTheme) :
        deepMerge(defaultTheme, this.options.theme)
      this.optionsClass.lineSpacing = this.options.lineSpace ?? 12
      this.optionsClass.inlineLineSpacing = this.options.inlineLineSpace ?? LengthMetrics.vp(12)
      this.optionsClass.lineHeightMultiple = this.options.lineHeightMultiple
      this.optionsClass.maxLines = this.options.maxLines
      // 回调挂在本实例的 optionsClass 上（随组件销毁而释放，不跨实例共享）
      this.optionsClass.linkClick = this.options.linkClick
      this.optionsClass.imageClick = this.options.imageClick
      this.optionsClass.customInlineBuilder = this.options.customInlineBuilder
      this.optionsClass.customBlockBuilder = this.options.customBlockBuilder
    }
  }

  build() {
    if (this.tokenList.length != 0) {
      MarkdownComponent({ tokenList: this.tokenList, options: this.optionsClass })
    }
  }
}
