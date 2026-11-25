/**
 * @Author : lcc
 * @CreateData : 2024/7/5
 * @Description: 默认主题
 */
import { MarkdownFontStyle, MarkdownTheme } from './MarkdownTheme'

const defaultFontStyle: MarkdownFontStyle = {
  fontWeight: FontWeight.Normal,
  fontColor: Color.Black,
  fontSize: 16
}
const defaultDarkFontStyle: MarkdownFontStyle = {
  fontWeight: FontWeight.Normal,
  fontColor: '#FFFFFF',
  fontSize: 16
}

export const defaultDarkTheme: MarkdownTheme = {
  backgroundColor: '#1E1F22',
  themeColor: '#6B9BFA',
  fontStyle: defaultDarkFontStyle,
  headingStyle: [
    {
      fontWeight: FontWeight.Bolder,
      fontColor: '#FFFFFF',
      fontSize: 30,
    },
    {
      fontWeight: FontWeight.Bold,
      fontColor: '#FFFFFF',
      fontSize: 28
    },
    {
      fontWeight: FontWeight.Medium,
      fontColor: '#FFFFFF',
      fontSize: 26
    },
    {
      fontWeight: FontWeight.Regular,
      fontColor: '#FFFFFF',
      fontSize: 24
    },
    {
      fontWeight: FontWeight.Normal,
      fontColor: '#FFFFFF',
      fontSize: 22
    },
    {
      fontWeight: FontWeight.Normal,
      fontColor: '#FFFFFF',
      fontSize: 18
    },
  ],
  blockQuoteStyle: {
    borderRadius: 4,
    driveWidth: 2,
    driveColor: '#485C84',
    backgroundColor: '#303236',
  },

  tableStyle: {
    driveWidth: 0.5,
    driveColor: '#FFFFFF'
  },
  listStyle: {
    marginLeft: 8
  },
  paragraphStyle: defaultDarkFontStyle,
  latexStyle: {
    fontSize: 22,
    fontColor: 0xffffffff,
    backgroundColor: 0x00000000
  },
  code: {
    fontColor: {
      'text': '#FFFFFF',
      'string': '#FFFFFF',
      'keyword': '#0A69DA',
      'type': '#0A69DA',
      'symbol': '#E3DA90',
      'number': '#B3E54C',
      'boolean': '#FFFFFF',
    },
    backgroundColor: '#303236',
    borderRadius: 4,
  },
  codeSpan: {
    backgroundColor: '#303236',
    borderRadius: 4
  },
  hrStyle: {
    driveColor: '#393B41',
    driveWidth: 1
  },

  linkColor: '#6A9BFA',
  imageObjectFit: ImageFit.Contain,
  // html?: MarkdownFontStyle
}


export const defaultTheme: MarkdownTheme = {
  backgroundColor: '#FFFFFF',
  themeColor: '#6B9BFA',
  fontStyle: defaultFontStyle,
  headingStyle: [
    {
      fontWeight: FontWeight.Bolder,
      fontColor: '#000000',
      fontSize: 30,
    },
    {
      fontWeight: FontWeight.Bold,
      fontColor: '#000000',
      fontSize: 28
    },
    {
      fontWeight: FontWeight.Medium,
      fontColor: '#000000',
      fontSize: 26
    },
    {
      fontWeight: FontWeight.Regular,
      fontColor: '#000000',
      fontSize: 24
    },
    {
      fontWeight: FontWeight.Normal,
      fontColor: '#000000',
      fontSize: 22
    },
    {
      fontWeight: FontWeight.Lighter,
      fontColor: '#000000',
      fontSize: 20
    },
  ],
  blockQuoteStyle: {
    borderRadius: 4,
    driveWidth: 2,
    driveColor: '#A6BAE1',
    backgroundColor: '#F5F7F9',
  },

  tableStyle: {
    driveWidth: 0.5,
    driveColor: '#EBECF0'
  },
  listStyle: {
    marginLeft: 8
  },
  // ✅ 修正了最初的 Bug：白天模式的段落使用黑色字体
  paragraphStyle: defaultFontStyle, 
  latexStyle: {
    fontSize: 22,
    fontColor: 0xff000000,
    backgroundColor: 0x00000000
  },
  code: {
    fontColor: {
      'text': Color.White,
      'string': Color.White,
      'keyword': '#0A69DA',
      'type': '#0A69DA',
      'symbol': '#E3DA90',
      'number': '#B3E54C',
      'boolean': Color.White,
    },
    backgroundColor: '#303236',
    borderRadius: 4,
  },
  codeSpan: {
    backgroundColor: '#F5F7F9',
    borderRadius: 4
  },
  hrStyle: {
    driveColor: '#393B41',
    driveWidth: 1
  },

  linkColor: '#6A9BFA',
  imageObjectFit: ImageFit.Contain,
  // html?: MarkdownFontStyle
}