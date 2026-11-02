/**
 * LoadingState - the busy / failed panel for Settings > Models. Models/index.tsx
 * renders it twice (line 305 for the loading arm, line 307 for the error arm)
 * and is reached through the components barrel: Models/index.tsx:14 ->
 * components/index.ts:2 -> components/sections/index.ts:1.
 *
 * What this file pins:
 *   1. the message text is rendered verbatim - the error arm passes a raw error
 *      string, not an i18n key, so nothing may re-translate or truncate it;
 *   2. the error colour is applied ONLY by the `error` prop, and applied as the
 *      css custom property so a theme change recolours it without a rebuild;
 *   3. the retry button sits behind a COMPOUND guard (`error && onRetry`):
 *      an error without a retry handler must colour the text but render no
 *      button, and a retry handler without `error` must render none either. A
 *      button that cannot retry is worse than no button;
 *   4. clicking the button invokes the caller's handler (Models/index.tsx wires
 *      it to fetchAll), and the handler is called once per click;
 *   5. the retry label is the i18n key the product itself asks for
 *      (`models.retry`, present in src/locales/en.json as "Retry");
 *   6. an optional className is appended to the module class, and omitting it
 *      leaves the module class as the single entry rather than injecting
 *      "undefined";
 *   7. the button keeps the 12px top margin that separates it from the message.
 *
 * The global design stub renders Button as a real <button> that forwards
 * onClick and style, so both are observable in the DOM here and no per-file
 * stub is needed.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { LoadingState } from "./LoadingState";
import styles from "../../index.module.less";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

describe("LoadingState message", () => {
  beforeEach(() => {
    // The module keys are real generated class names; asserting equality
    // against them would pass vacuously if a key ever went missing.
    expect(typeof styles.loading).toBe("string");
    expect(styles.loading.length).toBeGreaterThan(0);
    expect(typeof styles.loadingText).toBe("string");
    expect(styles.loadingText.length).toBeGreaterThan(0);
  });

  it("renders the message text verbatim", () => {
    const { container } = render(<LoadingState message="models.loading" />);
    expect(container.querySelector("span")?.textContent).toBe("models.loading");
  });

  it("renders a raw error string without translating it", () => {
    const raw = "Request failed with status code 502";
    const { container } = render(<LoadingState message={raw} error />);
    expect(container.querySelector("span")?.textContent).toBe(raw);
  });

  it("applies the module classes to the wrapper and the text", () => {
    const { container } = render(<LoadingState message="m" />);
    const wrapper = container.querySelector("div");
    expect(wrapper?.classList.contains(styles.loading)).toBe(true);
    expect(container.querySelector("span")?.className).toBe(styles.loadingText);
  });
});

describe("LoadingState error colour", () => {
  it("leaves the colour unset while merely loading", () => {
    const { container } = render(<LoadingState message="m" />);
    expect(container.querySelector("span")?.getAttribute("style")).toBeNull();
  });

  it("sets the error custom property when error is true", () => {
    const { container } = render(<LoadingState message="m" error />);
    expect(container.querySelector("span")?.style.color).toBe(
      "var(--app-error-text)",
    );
  });

  it("does not colour the text when error is false", () => {
    const { container } = render(<LoadingState message="m" error={false} />);
    expect(container.querySelector("span")?.getAttribute("style")).toBeNull();
  });
});

describe("LoadingState retry button guard", () => {
  it("renders the retry button only when error AND onRetry are both present", () => {
    const onRetry = vi.fn();
    const { container } = render(
      <LoadingState message="m" error onRetry={onRetry} />,
    );
    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toBe("models.retry");
  });

  it("renders no button for an error that has no retry handler", () => {
    const { container } = render(<LoadingState message="m" error />);
    // The text is still coloured: the failure is reported, only the retry
    // affordance is withheld.
    expect(container.querySelector("span")?.style.color).toBe(
      "var(--app-error-text)",
    );
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("renders no button for a retry handler supplied without error", () => {
    const { container } = render(
      <LoadingState message="m" onRetry={vi.fn()} />,
    );
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("renders no button when onRetry is undefined explicitly", () => {
    const { container } = render(
      <LoadingState message="m" error onRetry={undefined} />,
    );
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });
});

describe("LoadingState retry click", () => {
  it("calls the handler once per click", () => {
    const onRetry = vi.fn();
    const { container } = render(
      <LoadingState message="m" error onRetry={onRetry} />,
    );
    const button = container.querySelector("button");
    expect(onRetry).not.toHaveBeenCalled();
    fireEvent.click(button!);
    expect(onRetry).toHaveBeenCalledTimes(1);
    fireEvent.click(button!);
    expect(onRetry).toHaveBeenCalledTimes(2);
  });

  it("keeps the margin that separates the button from the message", () => {
    const { container } = render(
      <LoadingState message="m" error onRetry={vi.fn()} />,
    );
    const button = container.querySelector("button");
    expect(button?.style.marginTop).toBe("12px");
  });
});

describe("LoadingState className", () => {
  it("appends a caller className to the module class", () => {
    const { container } = render(
      <LoadingState message="m" className="models-inline-state" />,
    );
    const classes = Array.from(
      container.querySelector("div")!.classList,
    ).filter(Boolean);
    expect(classes).toEqual([styles.loading, "models-inline-state"]);
  });

  it("keeps the module class as the only entry when className is omitted", () => {
    const { container } = render(<LoadingState message="m" />);
    const classes = Array.from(
      container.querySelector("div")!.classList,
    ).filter(Boolean);
    expect(classes).toEqual([styles.loading]);
    // Guards against the template literal leaking "undefined" or "null".
    expect(container.querySelector("div")!.className).not.toContain(
      "undefined",
    );
    expect(container.querySelector("div")!.className).not.toContain("null");
  });

  it("keeps the module class as the only entry when className is empty", () => {
    const { container } = render(<LoadingState message="m" className="" />);
    const classes = Array.from(
      container.querySelector("div")!.classList,
    ).filter(Boolean);
    expect(classes).toEqual([styles.loading]);
  });
});
