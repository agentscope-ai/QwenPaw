export type CodeType = 'code' | 'keyword' | 'type' | 'number' | 'symbol' | 'string' | 'text' | 'boolean'

export interface CodeToken {
  type: CodeType,
  text: string
}

// 匹配带转义的字符串字面量（单/双引号）。
// 注意：不要使用 (["'])(?:(?=(\\?))\2.)*?\1 一类含嵌套量词的写法，
// 对未闭合引号 + 长反斜杠串存在灾难性回溯（ReDoS）；当前写法为线性时间。
const stringRegex = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g
const commonRegex = (/([(\s=){}."])/gi)

function splitOne(code: CodeToken, token: CodeToken): CodeToken[] {
  if (!code) {
    return []
  } else if (code.type !== 'code') {
    return [code]
  } else {
    let res: CodeToken[] = []
    let split = code.text.split(token.text)
    split.forEach((v, index) => {
      if (index < split.length - 1) {
        res.push({
          type: 'code',
          text: v
        })
        res.push({
          type: 'string',
          text: token.text
        })
      } else {
        res.push({
          type: 'code',
          text: v
        })
      }
    })
    return res
  }
}

function split(codes: CodeToken[], token: CodeToken): CodeToken[] {
  if (!codes || codes.length <= 0) {
    return []
  }
  let res: CodeToken[] = []
  codes.forEach(code => {
    res = res.concat(splitOne(code, token))
  })
  return res
}


function stringSplit(code: string): CodeToken[] {
  let tokens: CodeToken[] = [{ type: 'code', text: code }]
  //先将字符串分割出来
  let strings = code.match(stringRegex)
  if (!strings || strings.length <= 0) {
    return tokens
  }
  for (let i = 0; i < strings.length; i++) {
    tokens = split(tokens, { type: 'string', text: strings[i] })
  }
  return tokens
}


const keywords: Set<string> = new Set([
  'public', 'private', 'protect', 'default',
  'new', 'throw', 'throws', 'let', 'var', 'const',
  'if', 'else', 'switch', 'case', 'default', 'for', 'continue', 'break',
  'static', 'function', 'const', 'class', 'interface', 'extends', 'extend', 'implements', 'implement', 'type', 'export',
  '@param'
])

const types: Set<string> = new Set([
  'void', 'bool', 'boolean', 'byte', 'short', 'int', 'integer', 'long', 'float', 'double', 'char', 'character',
  'number', 'string', 'array', 'object'
])

const symbols: Set<string> = new Set([
  '=', '(', ')', '{', '}', '<', '>', '|', '&', '!', ';', ':', '.', '^', '$', '@', '%', '+', '-', '*', '/'
])

function isNumber(str: string) {
  return !isNaN(parseFloat(str)) && isFinite(Number(str));
}

function buildToken(text: string) {
  // if (/^[-+]?\d*\.?\d+$/.test(text.trim())) {
  if (isNumber(text.trim())) {
    return {
      type: 'number',
      text: text
    } as CodeToken
  } else if ('true' === text.trim() || 'false' === text.trim()) {
    return {
      type: 'boolean',
      text: text
    } as CodeToken
  } else if (keywords.has(text.trim().toLowerCase())) {
    return {
      type: 'keyword',
      text: text
    } as CodeToken
  } else if (types.has(text.trim().toLowerCase())) {
    return {
      type: 'type',
      text: text
    } as CodeToken
  } else if (symbols.has(text.trim())) {
    return {
      type: 'symbol',
      text: text
    } as CodeToken
  } else {
    return {
      type: 'text',
      text: text
    } as CodeToken
  }
}

function commonSplit(token: CodeToken): CodeToken[] {
  if (token.type === 'code') {
    let split = token.text.split(commonRegex)
    return split.map((s: string): CodeToken => {
      return buildToken(s);
    })
  } else {
    return [token]
  }
}

export function highlightCodeAnalyzer(code: string): CodeToken[] {
  let sTokens = stringSplit(code)
  // console.log(JSON.stringify(sTokens))
  //开始一般分词
  let tokens: CodeToken[] = []
  for (let i = 0; i < sTokens.length; i++) {
    tokens = tokens.concat(commonSplit(sTokens[i]))
  }
  // console.log(JSON.stringify(tokens))
  return tokens
}