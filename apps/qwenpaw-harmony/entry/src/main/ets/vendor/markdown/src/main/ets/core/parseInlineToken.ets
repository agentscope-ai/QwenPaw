/**
 * @Author : lcc
 * @CreateData : 2024/7/4
 * @Description:
 */
import { MarkdownTheme } from '../config/MarkdownTheme'
import { markdown, MarkdownOptionsClass } from '../Index'
import { clearMarkdown, latexToPixelMap } from '../utils'
import { Token } from './Tokens'
import { LengthMetrics } from '@kit.ArkUI'

export interface InlineParams {
  token: Token[],
  theme: MarkdownTheme,
  uiContext: UIContext,
  inlineTextStyle?: MutableStyledString,
  isLink?: boolean
  fontWeight?: FontWeight,
  // 斜体/删除线随递归传播，保证嵌套强调（如 *a ~~b~~ c*）样式正确
  fontStyle?: FontStyle,
  lineThrough?: boolean,
  onSpanClick?: () => void
  // 所属 Markdown 组件实例的 options，携带 linkClick/imageClick 等回调，
  // 避免多实例共用模块级回调时互相覆盖
  options?: MarkdownOptionsClass
}

/**
 * 追加一段行内文本并应用字体样式（颜色/粗细/斜体/删除线/手势）。
 * 供 text / strong 等"叶子"分支复用，保证递归传播来的样式被统一应用。
 */
function appendStyledText(params: InlineParams, rawText: string): void {
  const text = clearMarkdown(rawText)
  const style = params.inlineTextStyle
  if (!style) {
    return
  }
  const fontColor = params?.isLink ? params.theme?.linkColor : params.theme.fontStyle?.fontColor
  style.appendStyledString(new MutableStyledString(text, [{
    start: 0,
    length: text.length,
    styledKey: StyledStringKey.FONT,
    styledValue: new TextStyle({
      fontColor: fontColor,
      fontWeight: params?.fontWeight ?? params?.theme?.fontStyle?.fontWeight,
      fontStyle: params.fontStyle
    })
  }, {
    start: 0,
    length: text.length,
    styledKey: StyledStringKey.GESTURE,
    styledValue: new GestureStyle({ onClick: params.onSpanClick })
  }]))
  if (params.lineThrough) {
    try {
      style.setStyle({
        start: style.length - text.length,
        length: text.length,
        styledKey: StyledStringKey.DECORATION,
        styledValue: new DecorationStyle({
          type: TextDecorationType.LineThrough,
          color: fontColor,
          style: TextDecorationStyle.SOLID
        })
      })
    } catch (_) {
    }
  }
}

export async function parseInlineToken(params: InlineParams): Promise<MutableStyledString | undefined> {
  if (params.inlineTextStyle == undefined) {
    params.inlineTextStyle = new MutableStyledString('')
  }

  for (let i = 0; i < params.token.length; i++) {
    let tokenItem = params.token[i]

    if (tokenItem.type === 'image') {
      params.inlineTextStyle.appendStyledString(new MutableStyledString(new ImageAttachment({
        resourceValue: tokenItem.href,
        verticalAlign: ImageSpanAlignment.CENTER,
        size: { width: '100%' },
        objectFit: params.theme?.imageObjectFit,
      })))
      try {
        params.inlineTextStyle.setStyle({
          start: params.inlineTextStyle.length - 1,
          length: 1,
          styledKey: StyledStringKey.GESTURE,
          styledValue: new GestureStyle({
            onClick: () => {
              (params.options?.imageClick ?? markdown.registerImageClick)?.(tokenItem['href'])
            }
          })
        })
      } catch (_) {
      }
    } else if (tokenItem.type === 'br') {
      params.inlineTextStyle.appendStyledString(new MutableStyledString('\n'))
    } else if (tokenItem.type === 'strong') {
      if (tokenItem.tokens?.length != 0) {
        await parseInlineToken({
          token: tokenItem.tokens ?? [],
          theme: params.theme,
          inlineTextStyle: params.inlineTextStyle,
          fontWeight: FontWeight.Bold,
          isLink: params.isLink,
          uiContext: params.uiContext,
          onSpanClick: params.onSpanClick,
          options: params.options,
          fontStyle: params.fontStyle,
          lineThrough: params.lineThrough
        })
      } else {
        appendStyledText(params, tokenItem.text)
      }
    } else if (tokenItem.type === 'del') {
      if (tokenItem.tokens?.length != 0) {
        // 嵌套内容递归渲染并传播删除线（~~a **b**~~ 的加粗需保留）
        await parseInlineToken({
          token: tokenItem.tokens ?? [],
          theme: params.theme,
          inlineTextStyle: params.inlineTextStyle,
          isLink: params.isLink,
          uiContext: params.uiContext,
          onSpanClick: params.onSpanClick,
          options: params.options,
          fontWeight: params.fontWeight,
          fontStyle: params.fontStyle,
          lineThrough: true
        })
      } else {
        let text = clearMarkdown(tokenItem.text)
        params.inlineTextStyle.appendStyledString(new MutableStyledString(text,
          [{
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.DECORATION,
            styledValue: new DecorationStyle({
              type: TextDecorationType.LineThrough,
              color: params?.isLink ? params.theme?.linkColor : params.theme.fontStyle?.fontColor,
              style: TextDecorationStyle.SOLID
            })
          }, {
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.FONT,
            styledValue: new TextStyle({
              fontColor: params?.isLink ? params.theme?.linkColor : params.theme.fontStyle?.fontColor,
            })
          }, {
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.GESTURE,
            styledValue: new GestureStyle({ onClick: params.onSpanClick })
          }]))
      }
    } else if (tokenItem.type === 'text') {
      appendStyledText(params, tokenItem.text)
    } else if (tokenItem.type === 'em') {
      if (tokenItem.tokens?.length != 0) {
        // 嵌套内容递归渲染并传播斜体（*a **b** c* 的加粗需保留）
        await parseInlineToken({
          token: tokenItem.tokens ?? [],
          theme: params.theme,
          inlineTextStyle: params.inlineTextStyle,
          isLink: params.isLink,
          uiContext: params.uiContext,
          onSpanClick: params.onSpanClick,
          options: params.options,
          fontWeight: params.fontWeight,
          fontStyle: FontStyle.Italic,
          lineThrough: params.lineThrough
        })
      } else {
        let text = clearMarkdown(tokenItem.text)
        params.inlineTextStyle.appendStyledString(new MutableStyledString(text,
          [{
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.FONT,
            styledValue: new TextStyle({
              fontColor: params?.isLink ? params.theme?.linkColor : params.theme.fontStyle?.fontColor,
              fontStyle: FontStyle.Italic
            })
          }, {
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.GESTURE,
            styledValue: new GestureStyle({ onClick: params.onSpanClick })
          }]))
      }
    } else if (tokenItem.type === 'codespan') {
      let codeSpan = `  ${clearMarkdown(tokenItem.text)}  `
      params.inlineTextStyle.appendStyledString(new MutableStyledString(codeSpan,
        [{
          start: 0,
          length: codeSpan.length,
          styledKey: StyledStringKey.FONT,
          styledValue: new TextStyle({
            fontColor: params.theme?.fontStyle?.fontColor
          })
        }, {
          start: 0,
          length: codeSpan.length,
          styledKey: StyledStringKey.BACKGROUND_COLOR,
          styledValue: new BackgroundColorStyle({
            color: params.theme?.codeSpan?.backgroundColor,
            radius: params.theme?.codeSpan?.borderRadius
          })
        }]))
    } else if (tokenItem.type === 'link') {
      await parseInlineToken({
        token: tokenItem.tokens ?? [],
        theme: params.theme,
        inlineTextStyle: params.inlineTextStyle,
        fontWeight: params.fontWeight,
        uiContext: params.uiContext,
        isLink: true,
        onSpanClick: () => {
          (params.options?.linkClick ?? markdown.registerLinkClick)?.(tokenItem['href'])
        },
        options: params.options,
        fontStyle: params.fontStyle,
        lineThrough: params.lineThrough
      })
    } else if (tokenItem.type === 'sup' || tokenItem.type === 'sub') {
      if (tokenItem.tokens?.length != 0) {
        let baseFontSize = (params.theme?.fontStyle?.fontSize as number) || 16;
        let smallFontSize = baseFontSize * 0.75;
        let text = clearMarkdown(tokenItem.text);
        let offset = tokenItem.type === 'sup' ? baseFontSize * 0.3 : -baseFontSize * 0.3;
        
        params.inlineTextStyle.appendStyledString(new MutableStyledString(text,
          [{
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.FONT,
            styledValue: new TextStyle({
              fontColor: params?.isLink ? params.theme?.linkColor : params.theme.fontStyle?.fontColor,
              fontWeight: params?.fontWeight ?? params?.theme?.fontStyle?.fontWeight,
              fontSize: LengthMetrics.vp(smallFontSize)
            })
          }, {
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.BASELINE_OFFSET,
            styledValue: new BaselineOffsetStyle(LengthMetrics.vp(offset))
          }, {
            start: 0,
            length: text.length,
            styledKey: StyledStringKey.GESTURE,
            styledValue: new GestureStyle({ onClick: params.onSpanClick })
          }]))
      }
    } else if (tokenItem.type === 'inlineLatex') {
      let imageInfo = await latexToPixelMap(tokenItem.text, params.uiContext.fp2px(params.theme.latexStyle?.fontSize),
        params.theme.latexStyle?.fontColor ?? 0xffffffff, params.theme.latexStyle?.backgroundColor ?? 0xffffffff)
      params.inlineTextStyle.appendStyledString(new MutableStyledString(new ImageAttachment({
        value: imageInfo.pixelMap,
        verticalAlign: ImageSpanAlignment.CENTER,
        size: {
          width: params.uiContext.px2vp(imageInfo.width),
          height: params.uiContext.px2vp(imageInfo.height)
        },
        objectFit: ImageFit.Contain,
      })))
      // }  else if (tokenItem.type === 'html') {
      //   // 从当前i忘下找 找到最近的html
      //   let htmlToken: string = tokenItem.text;
      //   for (let j = i + 1; j < params.token.length; j++) {
      //     let htmlTokenItem = params.token[j]
      //     htmlToken += htmlTokenItem['text']
      //     if (htmlTokenItem.type == 'html') {
      //       break;
      //     }
      //   }
      //   htmlToken
      // params.token.slice()
      // Span(tokenItem.text)
      // let text = await StyledString.fromHtml(tokenItem.text)
      // this.inlineTextStyle.appendStyledString(text)
    } else {
      (params.options?.customInlineBuilder ?? markdown.customInlineBuilder)?.(tokenItem, params)
    }
  }
  return params.inlineTextStyle
}
