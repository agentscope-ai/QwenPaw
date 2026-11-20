import { TokenizerExtension } from './core'
import { Tokens, Token } from './core/Tokens'

export const superscriptExtension: TokenizerExtension = {
  name: 'sup',
  level: 'inline',
  start(src) { return src.match(/\^/)?.index; },
  tokenizer(src, tokens) {
    const rule = /^\^([^\^]+)\^/;
    const match = rule.exec(src);
    if (match) {
      return {
        type: 'sup',
        raw: match[0],
        text: match[1],
        tokens: this.lexer.inlineTokens(match[1])
      };
    }
    return undefined;
  }
};

export const subscriptExtension: TokenizerExtension = {
  name: 'sub',
  level: 'inline',
  start(src) { return src.match(/~/)?.index; },
  tokenizer(src, tokens) {
    // We make sure it doesn't match standard strikethrough ~~...~~
    const rule = /^~([^~]+)~/;
    const match = rule.exec(src);
    if (match && !src.startsWith('~~')) {
      return {
        type: 'sub',
        raw: match[0],
        text: match[1],
        tokens: this.lexer.inlineTokens(match[1])
      };
    }
    return undefined;
  }
};
