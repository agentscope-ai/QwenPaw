import type { MarkedExtension } from "marked";
import type { Options as RemarkGfmOptions } from "remark-gfm";

/**
 * Marked extension that restricts GFM strikethrough to double tildes
 * (`~~...~~`) so single `~` characters (such as numeric ranges `600~1500 t/s`)
 * stay literal.
 */
export const DOUBLE_TILDE_MARKED_CONFIG: MarkedExtension = {
  tokenizer: {
    del(src: string) {
      if (!src.startsWith("~~")) {
        return undefined;
      }
      return false;
    },
  },
};

/** remark-gfm options disabling single-tilde strikethrough. */
export const DOUBLE_TILDE_REMARK_GFM_OPTIONS: RemarkGfmOptions = {
  singleTilde: false,
};
