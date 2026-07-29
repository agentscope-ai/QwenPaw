/**
 * RobotFramework language support for Monaco.
 *
 * Monaco does not ship a RobotFramework definition, so `.robot` and
 * `.resource` files fell back to plaintext in the Coding Mode editor.
 * This module registers a Monarch tokenizer covering section headers,
 * settings, control-flow keywords, variables, tags and comments.
 *
 * Registered once from `monacoSetup.ts` (side-effect free by itself;
 * call `registerRobotFramework` with a Monaco instance).
 */

import type * as Monaco from "monaco-editor";

export const ROBOT_LANGUAGE_ID = "robotframework";

export const conf: Monaco.languages.LanguageConfiguration = {
  comments: { lineComment: "#" },
  brackets: [
    ["{", "}"],
    ["[", "]"],
    ["(", ")"],
  ],
  autoClosingPairs: [
    { open: "{", close: "}" },
    { open: "[", close: "]" },
    { open: "(", close: ")" },
  ],
  surroundingPairs: [
    { open: "{", close: "}" },
    { open: "[", close: "]" },
    { open: "(", close: ")" },
  ],
};

/**
 * Monarch grammar.
 *
 * RobotFramework separates cells with 2+ spaces or 1+ tabs, so keyword
 * rules assert a cell boundary via `(?= {2,}|\t+|[ \t]*$)`.
 * Token names reuse Monaco's built-in theme colors (keyword, comment,
 * variable, tag, type, number) so both `vs` and `vs-dark` work.
 */
export const language: Monaco.languages.IMonarchLanguage = {
  defaultToken: "",
  ignoreCase: true,
  tokenizer: {
    root: [
      // Section headers: *** Settings ***, *** Test Cases *** …
      [
        /^\*+[ \t]*(settings?|variables?|test cases?|tasks?|keywords?|comments?)\b[ \t*]*$/,
        "keyword.section",
      ],
      // Line continuation marker
      [/^[ \t]*\.\.\.(?=[ \t]|$)/, "delimiter"],
      // Control-flow structures at cell start (FOR / IF / TRY …)
      [
        /^[ \t]*(FOR|END|IF|ELSE IF|ELSE|WHILE|TRY|EXCEPT|FINALLY|RETURN|BREAK|CONTINUE|VAR|GROUP)(?= {2,}|\t+|[ \t]*$)/,
        "keyword.control",
      ],
      // Gherkin-style prefixes in keyword calls
      [/^[ \t]+(given|when|then|and|but)(?=[ \t])/, "keyword.control"],
      // Settings-section directives at column 0
      [
        /^(library|resource|variables|documentation|metadata|name|suite setup|suite teardown|test setup|test teardown|test template|test timeout|test tags|task setup|task teardown|task template|task timeout|task tags|force tags|default tags|keyword tags)(?= {2,}|\t+|[ \t]*$)/,
        "keyword",
      ],
      // Test case / task / keyword definition name at column 0
      [/^[^ \t#*$@&%\\[].*$/, "type"],
      // [Tags] / [Arguments] … bracket settings
      [
        /\[(documentation|tags|arguments|setup|teardown|template|timeout|return|precondition|postcondition)\]/,
        "tag",
      ],
      // Escaped characters (\# is not a comment, \${ not a variable)
      [/\\./, "string.escape"],
      // Comments in the first cell or after a cell separator
      [/^[ \t]*#.*$/, "comment"],
      [/(?: {2,}|\t+)[ \t]*#.*$/, "comment"],
      // Variables: ${scalar} @{list} &{dict} %{env}
      [/[$@&%]\{/, { token: "variable", next: "@variable" }],
      // FOR loop separators as standalone cells
      [
        /\b(IN RANGE|IN ENUMERATE|IN ZIP|IN)(?= {2,}|\t+|[ \t]*$)/,
        "keyword.control",
      ],
      // Numbers
      [/\b\d+(\.\d+)?\b/, "number"],
      // Cell separators & plain text
      [/[ \t]+/, "white"],
      [/[^ \t$@&%#\\]+/, ""],
      [/./, ""],
    ],
    // Inside ${ … } — supports nesting like ${outer_${inner}}
    variable: [
      [/[$@&%]\{/, { token: "variable", next: "@push" }],
      [/\}/, { token: "variable", next: "@pop" }],
      [/[^$@&%{}]+/, "variable"],
      [/./, "variable"],
    ],
  },
};

/**
 * Register RobotFramework with the given Monaco instance.
 * Safe to call multiple times — skips if already registered.
 */
export function registerRobotFramework(monaco: typeof Monaco): void {
  const alreadyRegistered = monaco.languages
    .getLanguages()
    .some((lang) => lang.id === ROBOT_LANGUAGE_ID);
  if (alreadyRegistered) return;

  monaco.languages.register({
    id: ROBOT_LANGUAGE_ID,
    extensions: [".robot", ".resource"],
    aliases: ["RobotFramework", "robotframework", "Robot Framework"],
  });
  monaco.languages.setLanguageConfiguration(ROBOT_LANGUAGE_ID, conf);
  monaco.languages.setMonarchTokensProvider(ROBOT_LANGUAGE_ID, language);
}
