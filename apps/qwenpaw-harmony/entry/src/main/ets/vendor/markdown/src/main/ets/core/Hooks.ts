import { _defaults } from './defaults';
import type { MarkedOptions } from './MarkedOptions';
import type { Token, TokensList } from './Tokens';

export class _Hooks {
  options: MarkedOptions;

  constructor(options?: MarkedOptions) {
    this.options = options || _defaults;
  }

  static passThroughHooks = new Set([
    'preprocess',
    'postprocess',
    'processAllTokens'
  ]);

  /**
   * Process markdown before marked
   */
  preprocess(markdown: string) {
    return markdown;
  }

  /**
   * Process HTML after marked is finished
   */
  postprocess(html: string) {
    return html;
  }

  /**
   * Process all tokens before walk tokens
   */
  processAllTokens(tokens: Token[] | TokensList) {
    return tokens;
  }
}
