import type { HostBundle } from "../types";

type HostReact = typeof import("react");

function highlightYamlLine(React: HostReact, line: string) {
  const span = (cls: string, text: string | number) =>
    React.createElement("span", { className: cls }, text);

  const listNodeMatch = line.match(/^(\s*- )(node_id)(:)( ?)(.+)$/);
  if (listNodeMatch) {
    return React.createElement(
      React.Fragment,
      null,
      span("datapaw-yaml-punctuation", listNodeMatch[1]),
      span(
        "datapaw-yaml-key",
        `${listNodeMatch[2]}${listNodeMatch[3]}`,
      ),
      listNodeMatch[4],
      span("datapaw-yaml-value", listNodeMatch[5]),
    );
  }

  const depListMatch = line.match(/^(\s+- )(.+)$/);
  if (depListMatch && !line.includes(":")) {
    return React.createElement(
      React.Fragment,
      null,
      span("datapaw-yaml-punctuation", depListMatch[1]),
      span("datapaw-yaml-value", depListMatch[2]),
    );
  }

  const kvMatch = line.match(/^(\s*)([A-Za-z_][\w]*)(:)( ?)(.*)$/);
  if (kvMatch) {
    return React.createElement(
      React.Fragment,
      null,
      kvMatch[1],
      span("datapaw-yaml-key", `${kvMatch[2]}${kvMatch[3]}`),
      kvMatch[4],
      span("datapaw-yaml-value", kvMatch[5]),
    );
  }

  return line || "\u00a0";
}

export function createYamlCodeEditor(host: HostBundle) {
  const { React } = host;
  const { useCallback, useMemo, useRef } = React;

  return function YamlCodeEditor({
    value,
    onChange,
    readOnly = false,
  }: {
    value: string;
    onChange: (value: string) => void;
    readOnly?: boolean;
  }) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const highlightRef = useRef<HTMLPreElement>(null);
    const lineNumbersRef = useRef<HTMLDivElement>(null);

    const lines = useMemo(() => value.split("\n"), [value]);
    const lineCount = Math.max(lines.length, 16);

    const syncScroll = useCallback(() => {
      const textarea = textareaRef.current;
      const highlight = highlightRef.current;
      const lineNumbers = lineNumbersRef.current;
      if (!textarea) return;
      if (highlight) {
        highlight.scrollTop = textarea.scrollTop;
        highlight.scrollLeft = textarea.scrollLeft;
      }
      if (lineNumbers) lineNumbers.scrollTop = textarea.scrollTop;
    }, []);

    return React.createElement(
      "div",
      { className: "datapaw-yaml-editor" },
      React.createElement(
        "div",
        {
          ref: lineNumbersRef,
          className: "datapaw-yaml-line-numbers",
          "aria-hidden": true,
        },
        Array.from({ length: lineCount }, (_, index) =>
          React.createElement(
            "div",
            { key: index + 1, className: "datapaw-yaml-line-number" },
            index + 1,
          ),
        ),
      ),
      React.createElement(
        "div",
        { className: "datapaw-yaml-code-area" },
        React.createElement(
          "pre",
          {
            ref: highlightRef,
            className: "datapaw-yaml-highlight",
            "aria-hidden": true,
          },
          lines.map((line, index) =>
            React.createElement(
              "div",
              { key: index, className: "datapaw-yaml-code-line" },
              highlightYamlLine(React, line),
            ),
          ),
        ),
        React.createElement("textarea", {
          ref: textareaRef,
          className: "datapaw-yaml-textarea",
          value,
          onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) =>
            onChange(event.target.value),
          onScroll: syncScroll,
          spellCheck: false,
          readOnly,
          "aria-label": "Plan YAML editor",
        }),
      ),
    );
  };
}
