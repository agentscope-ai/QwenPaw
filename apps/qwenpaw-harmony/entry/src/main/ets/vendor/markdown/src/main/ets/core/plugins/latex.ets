import { TokenizerExtension, Tokens } from "../marked";


const inlineRule = /^(\${1,2})(?!\$)((?:\\.|[^\\\n])*?(?:\\.|[^\\\n\$]))\1(?=[\s?!\.,:？！。，：]|$)/;

// 兼容 \( ... \) 行内公式定界符
const inlineParenRule = /^\\\(([\s\S]+?)\\\)/;

const blockRule = /^(\${1,2})\n((?:\\[^]|[^\\])+?)\n\1(?:\n|$)/;

// 兼容 \[ ... \] 块级公式定界符
const blockBracketRule = /^\\\[([\s\S]+?)\\\](?:\n|$)/;



export function latexBlock(): TokenizerExtension {
  return {
    name: 'blockLatex',
    level: 'block',
    tokenizer(src: string): Tokens.Generic | undefined {
      const match = src.match(blockRule);
      if (match) {
        return {
          type: 'blockLatex',
          raw: match[0],
          text: match[2].trim(),
          displayMode: match[1].length === 2,
        }
      }
      const bracketMatch = src.match(blockBracketRule);
      if (bracketMatch) {
        return {
          type: 'blockLatex',
          raw: bracketMatch[0],
          text: bracketMatch[1].trim(),
          displayMode: true,
        }
      }
      return undefined
    },
  }
}

export function latexInline(): TokenizerExtension {
  return {
    name: 'inlineLatex',
    level: 'inline',
    start: (src: string): number | void => {
      // 优先探测 \( 定界符
      const parenIdx = src.indexOf('\\(');
      let index = 0;
      let indexSrc = src
      while (indexSrc) {
        index = indexSrc.indexOf('$');
        if (index === -1) {
          break
        }
        if (index === 0 || indexSrc.charAt(index - 1) === ' ') {
          const possibleKatex = indexSrc.substring(index);

          if (possibleKatex.match(inlineRule)) {
            // 取 $ 与 \( 中更靠前的位置
            if (parenIdx !== -1 && parenIdx < index) {
              return parenIdx;
            }
            return index;
          }
        }

        indexSrc = indexSrc.substring(index + 1).replace(/^\$+/, '');
      }
      if (parenIdx !== -1) {
        return parenIdx;
      }
    },
    tokenizer: (src: string): Tokens.Generic | undefined => {
      const match = src.match(inlineRule);
      if (match) {
        return {
          type: 'inlineLatex',
          raw: match[0],
          text: match[2].trim(),
          displayMode: match[1].length === 2
        }
      }
      const parenMatch = src.match(inlineParenRule);
      if (parenMatch) {
        return {
          type: 'inlineLatex',
          raw: parenMatch[0],
          text: parenMatch[1].trim(),
          displayMode: false
        }
      }
      return undefined
    },
  }
}

