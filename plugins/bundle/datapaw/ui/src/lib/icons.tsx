import type { HostBundle } from "../types";

type HostReact = HostBundle["React"];

/** Magic-wand style icon for plan correction (no @ant-design/icons dependency). */
export function createHighlightIcon(React: HostReact) {
  return function HighlightIcon({ size = 14 }: { size?: number }) {
    return React.createElement(
      "svg",
      {
        width: size,
        height: size,
        viewBox: "0 0 14 14",
        fill: "none",
        xmlns: "http://www.w3.org/2000/svg",
        "aria-hidden": true,
        style: { verticalAlign: "-0.125em" },
      },
      React.createElement("path", {
        d: "M8.2 1.4l.4 1.6 1.6.4-1.6.4-.4 1.6-.4-1.6-1.6-.4 1.6-.4.4-1.6z",
        fill: "currentColor",
      }),
      React.createElement("path", {
        d: "M2.2 9.8l5.2-5.2 1.4 1.4-5.2 5.2H2.2V9.8z",
        stroke: "currentColor",
        strokeWidth: 1.2,
        strokeLinejoin: "round",
      }),
      React.createElement("path", {
        d: "M1.5 12.5h2.8",
        stroke: "currentColor",
        strokeWidth: 1.2,
        strokeLinecap: "round",
      }),
    );
  };
}

export function createCloseIcon(React: HostReact) {
  return function CloseIcon({ size = 12 }: { size?: number }) {
    return React.createElement(
      "svg",
      {
        width: size,
        height: size,
        viewBox: "0 0 12 12",
        fill: "none",
        xmlns: "http://www.w3.org/2000/svg",
        "aria-hidden": true,
      },
      React.createElement("path", {
        d: "M2 2l8 8M10 2L2 10",
        stroke: "currentColor",
        strokeWidth: 1.4,
        strokeLinecap: "round",
      }),
    );
  };
}
