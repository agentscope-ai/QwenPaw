/**
 * @Author : lcc
 * @CreateData : 2024/7/5
 * @Description:
 */

export interface MarkdownTheme {
  // 主题色
  themeColor?: ResourceColor
  backgroundColor?: ResourceColor
  fontStyle?: MarkdownFontStyle
  // 标题样式(h1-h6)
  headingStyle?: MarkdownFontStyle[],

  // 块样式
  blockQuoteStyle?: BlockQuoteStyle,

  // 表格样式
  tableStyle?: DriveStyle
  // 列表样式
  listStyle?: ListStyle,

  // 段落样式
  paragraphStyle?: MarkdownFontStyle,

  // latex 样式
  latexStyle?: LatexStyle,

  // 代码块及行内代码样式
  code?: CodeStyle,
  codeSpan?: CodeSpan,
  hrStyle?: DriveStyle,

  // 超链接字体颜色 不设置则为主题色
  linkColor?: ResourceColor
  imageObjectFit ?: ImageFit
  html?: MarkdownFontStyle
}


export interface CodeSpan {
  backgroundColor?: ResourceColor,
  borderRadius?: Dimension | BorderRadiuses,
}

export interface LinkTheme {
  fontColor?: ResourceColor
}

export interface ImageTheme {
  width?: Length
  height?: Length
  objectFit?: ImageFit
}

export interface MarkdownFontStyle {
  // 字体颜色
  fontColor?: ResourceColor
  // 字重
  fontWeight?: FontWeight
  // 字体大小
  fontSize?: Length,
  // lineSpacing?: LengthMetrics
}

export interface BlockQuoteStyle {
  backgroundColor?: ResourceColor;
  borderRadius?: Length,
  driveColor?: ResourceColor;
  driveWidth?: string | number
}


export interface DriveStyle {
  //线颜色和粗细
  driveColor?: ResourceColor;
  driveWidth?: string | number,
}


export interface ListStyle {
  marginLeft?: Length
}

export interface CodeStyle {
  fontColor?: Record<CodeHighLight, ResourceColor | undefined>,
  fontWeight?: FontWeight
  fontSize?: Length,
  backgroundColor?: ResourceColor,
  // 代码块边框色：未设置时不画边框（width 0），避免影响未声明边框的既有主题
  borderColor?: ResourceColor,
  borderRadius: Length | BorderRadiuses | LocalizedBorderRadiuses,
  codeSpanFontSize?: LengthMetrics,
  codeSpanBorderRadius ?: Dimension | BorderRadiuses,
  codeSpanBackgroundColor?: ResourceColor,
}

export interface LatexStyle {
  fontSize?: number,
  fontColor?: number,
  backgroundColor?: number
}

type CodeHighLight = 'string' | 'text' | 'keyword' | 'type' | 'symbol' | 'number' | 'boolean'


