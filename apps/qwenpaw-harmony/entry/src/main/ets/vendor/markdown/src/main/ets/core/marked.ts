import { _Lexer } from './Lexer';
import { _Parser } from './Parser';
import { _Tokenizer } from './Tokenizer';
import { _Renderer } from './Renderer';
import { _TextRenderer } from './TextRenderer';
import { _Hooks } from './Hooks';
import { Marked } from './Instance';
import {
  _getDefaults,
  changeDefaults,
  _defaults
} from './defaults';
import type { MarkedExtension, MarkedOptions } from './MarkedOptions';
import type { Token, TokensList } from './Tokens';
import type { MaybePromise } from './Instance';

const markedInstance = new Marked();

/**
 * Compiles markdown to HTML asynchronously.
 *
 * @param src String of markdown source to be compiled
 * @param options Hash of options, having async: true
 * @return Promise of string of compiled HTML
 */
export function marked(src: string, options: MarkedOptions & { async: true }): Promise<string>;

/**
 * Compiles markdown to HTML.
 *
 * @param src String of markdown source to be compiled
 * @param options Optional hash of options
 * @return String of compiled HTML. Will be a Promise of string if async is set to true by any extensions.
 */
export function marked(src: string, options?: MarkedOptions): string | Promise<string>;
export function marked(src: string, opt?: MarkedOptions): string | Promise<string> {
  return markedInstance.parse(src, opt);
}

/**
 * Sets the default options.
 *
 * @param options Hash of options
 */
marked.options =
marked.setOptions = function(options: MarkedOptions) {
  markedInstance.setOptions(options);
  marked.defaults = markedInstance.defaults;
  changeDefaults(marked.defaults);
  return marked;
};

/**
 * Gets the original marked default options.
 */
marked.getDefaults = _getDefaults;

marked.defaults = _defaults;

/**
 * Use Extension
 */

marked.use = function(...args: MarkedExtension[]) {
  markedInstance.use(...args);
  marked.defaults = markedInstance.defaults;
  changeDefaults(marked.defaults);
  return marked;
};

/**
 * Run callback for every token
 */

marked.walkTokens = function(tokens: Token[] | TokensList, callback: (token: Token) => MaybePromise | MaybePromise[]) {
  return markedInstance.walkTokens(tokens, callback);
};

/**
 * Compiles markdown to HTML without enclosing `p` tag.
 *
 * @param src String of markdown source to be compiled
 * @param options Hash of options
 * @return String of compiled HTML
 */
marked.parseInline = markedInstance.parseInline;

/**
 * Expose
 */
marked.Parser = _Parser;
marked.parser = _Parser.parse;
marked.Renderer = _Renderer;
marked.TextRenderer = _TextRenderer;
marked.Lexer = _Lexer;
marked.lexer = _Lexer.lex;
marked.Tokenizer = _Tokenizer;
marked.Hooks = _Hooks;
marked.parse = marked;

export const options = marked.options;
export const setOptions = marked.setOptions;
export const use = marked.use;
export const walkTokens = marked.walkTokens;
export const parseInline = marked.parseInline;
export const parse = marked;
export const parser = _Parser.parse;
export const lexer = _Lexer.lex;
export { _defaults as defaults, _getDefaults as getDefaults } from './defaults';
export { _Lexer as Lexer } from './Lexer';
export { _Parser as Parser } from './Parser';
export { _Tokenizer as Tokenizer } from './Tokenizer';
export { _Renderer as Renderer } from './Renderer';
export { _TextRenderer as TextRenderer } from './TextRenderer';
export { _Hooks as Hooks } from './Hooks';
export { Marked } from './Instance';
export  * from './MarkedOptions';
export  * from './rules';
export  * from './Tokens';
