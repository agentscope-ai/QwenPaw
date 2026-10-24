/**
 * @Author : lcc
 * @CreateData : 2024/7/4
 * @Description:
 */

import { MarkdownTheme } from '../config/MarkdownTheme'
import { Tokens } from '../core'
import { parseInlineToken } from '../core/parseInlineToken'
import { MarkdownOptionsClass } from '../Index'
import { textAlign } from '../utils'

export const defaultHorPadding: number = 20

export const itemLineHeight: number = 44


@ComponentV2
export struct Table {
  @Param @Require token: Tokens.Table
  @Param @Require options: MarkdownOptionsClass
  // 每一列最大宽度
  @Local itemMaxWidth: Map<number, number> = new Map()

  build() {

    Scroll() {
      Column() {
        TableHeader({
          tokens: this.token?.header,
          itemMaxWidth: this.itemMaxWidth,
          theme: this.options.theme,
          options: this.options
        })
        TableBody({
          tokens: this.token?.rows,
          itemMaxWidth: this.itemMaxWidth,
          theme: this.options.theme,
          options: this.options
        })
      }.alignItems(HorizontalAlign.Start)
    }
    .scrollable(ScrollDirection.Horizontal)
    .scrollBar(BarState.Off)
    .borderWidth(this.options.theme.tableStyle?.driveWidth)
    .borderColor(this.options.theme.tableStyle?.driveColor)

  }
}


@ComponentV2
export struct TableHeader {
  @Param @Require tokens: Tokens.TableCell[]
  @Param @Require theme: MarkdownTheme
  @Param @Require itemMaxWidth: Map<number, number>
  @Param @Require options: MarkdownOptionsClass


  build() {

    Row() {
      ForEach(this.tokens, (item: Tokens.TableCell, index: number) => {
        TableInline({
          tableCell: item,
          itemMaxWidth: this.itemMaxWidth,
          index: index,
          theme: this.theme,
          bold: true,
          options: this.options
        })

        if (index != this.tokens.length - 1) {
          Divider().color(this.theme?.tableStyle?.driveColor)
            .strokeWidth(this.theme?.tableStyle?.driveWidth)
            .vertical(true)
        }
      })
    }.border({
      width: {
        bottom: this.theme?.tableStyle?.driveWidth
      },
      color: this.theme?.tableStyle?.driveColor
    })

    .height(itemLineHeight)
  }
}


@ComponentV2
struct TableBody {
  @Param @Require tokens: Tokens.TableCell[][]
  @Param @Require theme: MarkdownTheme
  @Param @Require itemMaxWidth: Map<number, number>
  @Param @Require options: MarkdownOptionsClass

  build() {
    Column() {
      ForEach(this.tokens, (row: Tokens.TableCell[], _: number) => {
        Row() {
          ForEach(row, (item: Tokens.TableCell, index: number) => {

            TableInline({
              tableCell: item,
              itemMaxWidth: this.itemMaxWidth,
              index: index,
              theme: this.theme,
              options: this.options
            })

            if (index != row.length - 1) {
              Divider().color(this.theme?.tableStyle?.driveColor)
                .strokeWidth(this.theme?.tableStyle?.driveWidth)
                .vertical(true)
            }

          })
        }

        .height(itemLineHeight)
        .border({
          width: {
            bottom:this.theme?.tableStyle?.driveWidth
          },
          color: this.theme?.tableStyle?.driveColor
        })
      })
    }
  }
}


@ComponentV2
export struct TableInline {
  @Param @Require index: number
  @Param @Require tableCell: Tokens.TableCell
  @Param @Require itemMaxWidth: Map<number, number>
  @Param @Require theme: MarkdownTheme
  @Param bold: boolean = false
  @Param @Require options: MarkdownOptionsClass
  @Consumer() _mdInlineModifier?: AttributeModifier<TextAttribute>
  inlineTextController = new TextController()

  aboutToAppear(): void {
    this.watchToken()
  }

  @Monitor('theme')
  watchToken() {
    parseInlineToken({
      token: this.tableCell.tokens ?? [],
      theme: this.theme,
      // fontStyle: this.theme.fontStyle!,
      uiContext: this.getUIContext(),
      options: this.options
    }).then((data) => {
      this.inlineTextController.setStyledString(data)
    })
  }

  build() {
    Text(undefined, { controller: this.inlineTextController })
      .textAlign(textAlign(this.tableCell.align))
      .fontColor(this.theme?.fontStyle?.fontColor)
      .fontWeight(this.bold ? FontWeight.Bold : FontWeight.Normal)
      .padding({
        top: 10,
        bottom: 10,
        left: 8,
        right: 8
      })
      .maxLines(1)
      .fontSize(this.theme?.fontStyle?.fontSize)
      .width(this.itemMaxWidth[this.index])
      .onSizeChange((_: SizeOptions, newValue: SizeOptions) => {
        const width: number = this.itemMaxWidth[this.index]
        if (typeof newValue.width === 'number') {
          if (!width) {
            this.itemMaxWidth[this.index] = newValue.width + defaultHorPadding
          } else {
            if (newValue.width > width) {
              this.itemMaxWidth[this.index] = newValue.width + defaultHorPadding
            }
          }
        }
      })
  }
}
