/**
 * QrcodeAuthBlock - the QR-code authorization block reused by every channel
 * that authenticates by scanning (DingTalk, WeCom, ...). Real caller:
 * `ChannelDrawer.tsx:17` (import) with five render sites at `:397`, `:564`,
 * `:634`, `:1109`, `:1216`.
 *
 * This component is a thin adapter between two independent concerns:
 *   1. four presentational props (label / buttonText / imageAlt / hintText)
 *      that must land in exactly four different DOM positions, and
 *   2. everything else, which is forwarded verbatim to `useChannelQrcode`.
 *
 * The split matters because a regression that leaks a UI prop into the hook
 * config (or drops a hook field) is invisible to the caller: TypeScript still
 * compiles, the drawer still renders, and the QR flow simply stops polling.
 * So both directions are asserted here - what the hook receives AND what it
 * must not receive.
 *
 * Harness notes (probe-verified, not assumed):
 *   - The shared `src/test/design-mock.ts` stub renders `Button` as a bare
 *     `<button type="primary">`, dropping `loading` and `block` entirely, and
 *     renders `Form.Item` as `<div label="...">`, so the label is an attribute
 *     rather than visible text. Neither surface can carry the assertions this
 *     component needs, and the shared stub is off limits for modification, so
 *     this file installs its own `@agentscope-ai/design` stub that exposes
 *     `loading` / `block` as data attributes and renders the label as text.
 *   - `useChannelQrcode` is stubbed with an explicit state object instead of
 *     being driven through the API layer: the hook already has its own suite
 *     (`useChannelQrcode.test.ts`), and re-testing its polling here would make
 *     these assertions depend on timers.
 *   - The rgba colour strings asserted below were read off a real jsdom render
 *     (`style.color` serialises WITH the spaces: `rgba(255, 255, 255, 0.45)`),
 *     so they match both the source literal and the observed DOM value.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

const theme = vi.hoisted(() => ({ isDark: false }));

const qrState = vi.hoisted(() => ({
  qrcodeImg: "",
  loading: false,
}));

const fetchSpy = vi.hoisted(() => vi.fn());
const stopSpy = vi.hoisted(() => vi.fn());
const resetSpy = vi.hoisted(() => vi.fn());
/** Every config object the component hands to the hook, in call order. */
const cfgCalls = vi.hoisted(() => ({ list: [] as unknown[] }));

vi.mock("../../../../contexts/ThemeContext", () => ({
  useTheme: () => theme,
}));

vi.mock("./useChannelQrcode", () => ({
  useChannelQrcode: (config: unknown) => {
    cfgCalls.list.push(config);
    return {
      ...qrState,
      fetchQrcode: fetchSpy,
      stopPoll: stopSpy,
      reset: resetSpy,
    };
  },
}));

// Own stub, because the shared one cannot expose `loading` (see header).
vi.mock("@agentscope-ai/design", () => ({
  Button: ({
    children,
    onClick,
    loading,
    block,
    type,
  }: {
    children?: React.ReactNode;
    onClick?: () => void;
    loading?: boolean;
    block?: boolean;
    type?: string;
  }) =>
    React.createElement(
      "button",
      {
        type: "button",
        onClick,
        "data-loading": String(loading === true),
        "data-block": String(block === true),
        "data-variant": type,
      },
      children,
    ),
  Form: Object.assign(
    ({ children }: { children?: React.ReactNode }) =>
      React.createElement("div", { "data-stub": "form" }, children),
    {
      Item: ({
        children,
        label,
      }: {
        children?: React.ReactNode;
        label?: React.ReactNode;
      }) =>
        React.createElement(
          "div",
          { "data-stub": "form-item" },
          React.createElement("span", { "data-role": "item-label" }, label),
          children,
        ),
    },
  ),
}));

// antd's Spin is rendered by the component itself; stub it so the loading
// branch has a distinguishable observable instead of an anonymous <div>.
vi.mock("antd", () => ({
  Spin: () => React.createElement("div", { "data-role": "spin" }),
}));

import { QrcodeAuthBlock } from "./QrcodeAuthBlock";

const LABEL = "Scan to authorise";
const BUTTON_TEXT = "Get QR code";
const IMAGE_ALT = "WeChat QR Code";
const HINT_TEXT = "Scan with WeChat";

const onSuccess = vi.fn();
const onError = vi.fn();

const uiProps = {
  label: LABEL,
  buttonText: BUTTON_TEXT,
  imageAlt: IMAGE_ALT,
  hintText: HINT_TEXT,
};

const hookProps = {
  channel: "wechat",
  successStatus: "confirmed",
  successCredentialKey: "openid",
  onSuccess,
  onError,
};

const QR = "iVBORw0KGgoAAAANSUhEUg";

function setState(over: Partial<typeof qrState>) {
  qrState.qrcodeImg = "";
  qrState.loading = false;
  Object.assign(qrState, over);
}

function renderBlock(extra: Record<string, unknown> = {}) {
  return render(<QrcodeAuthBlock {...uiProps} {...hookProps} {...extra} />);
}

const img = (c: HTMLElement) => c.querySelector("img");
const spin = (c: HTMLElement) => c.querySelector('[data-role="spin"]');
const button = () => screen.getByRole("button", { name: BUTTON_TEXT });

describe("QrcodeAuthBlock - presentational props land in four distinct places", () => {
  it("renders the label as the Form.Item label text", () => {
    setState({});
    renderBlock();
    expect(screen.getByText(LABEL)).toBeTruthy();
    expect(screen.getByText(LABEL).dataset.role).toBe("item-label");
  });

  it("renders buttonText as the button's own text", () => {
    setState({});
    renderBlock();
    expect(button().textContent).toBe(BUTTON_TEXT);
  });

  it("uses imageAlt as the QR image's alt attribute", () => {
    setState({ qrcodeImg: QR });
    const { container } = renderBlock();
    expect(img(container)?.getAttribute("alt")).toBe(IMAGE_ALT);
  });

  it("renders hintText as the caption below the QR image", () => {
    setState({ qrcodeImg: QR });
    renderBlock();
    expect(screen.getByText(HINT_TEXT)).toBeTruthy();
  });
});

describe("QrcodeAuthBlock - the hook receives the config and nothing else", () => {
  it("forwards every non-UI prop to useChannelQrcode unchanged", () => {
    setState({});
    cfgCalls.list.length = 0;
    renderBlock({ pollInterval: 5000, maxPollCount: 3 });

    expect(cfgCalls.list.length).toBe(1);
    const cfg = cfgCalls.list[0] as Record<string, unknown>;
    expect(cfg.channel).toBe("wechat");
    expect(cfg.successStatus).toBe("confirmed");
    expect(cfg.successCredentialKey).toBe("openid");
    expect(cfg.pollInterval).toBe(5000);
    expect(cfg.maxPollCount).toBe(3);
    expect(cfg.onSuccess).toBe(onSuccess);
    expect(cfg.onError).toBe(onError);
  });

  it("keeps the four presentational props out of the hook config", () => {
    setState({});
    cfgCalls.list.length = 0;
    renderBlock();

    const cfg = cfgCalls.list[0] as Record<string, unknown>;
    // Probe-verified key set: exactly the five non-UI fields.
    expect(Object.keys(cfg).sort()).toEqual([
      "channel",
      "onError",
      "onSuccess",
      "successCredentialKey",
      "successStatus",
    ]);
    expect("label" in cfg).toBe(false);
    expect("buttonText" in cfg).toBe(false);
    expect("imageAlt" in cfg).toBe(false);
    expect("hintText" in cfg).toBe(false);
  });

  it("passes the callbacks through by identity, not by wrapper", () => {
    setState({});
    cfgCalls.list.length = 0;
    renderBlock();
    const cfg = cfgCalls.list[0] as Record<string, unknown>;
    // A wrapper would break the hook's identity-stable effect deps.
    expect(cfg.onSuccess).toBe(onSuccess);
    expect(cfg.onError).toBe(onError);
  });
});

describe("QrcodeAuthBlock - button wiring", () => {
  it("calls fetchQrcode when the button is clicked", () => {
    setState({});
    fetchSpy.mockClear();
    renderBlock();
    fireEvent.click(button());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("renders the button as primary and block, per the channel drawer layout", () => {
    setState({});
    renderBlock();
    expect(button().dataset.variant).toBe("primary");
    expect(button().dataset.block).toBe("true");
  });

  it("reflects the hook's loading flag on the button", () => {
    setState({ loading: true });
    renderBlock();
    expect(button().dataset.loading).toBe("true");
  });

  it("does not report loading when the hook is idle", () => {
    setState({ loading: false });
    renderBlock();
    expect(button().dataset.loading).toBe("false");
  });
});

describe("QrcodeAuthBlock - loading branch", () => {
  it("shows the spinner while loading", () => {
    setState({ loading: true });
    const { container } = renderBlock();
    expect(spin(container)).toBeTruthy();
  });

  it("hides the spinner once loading is over", () => {
    setState({ loading: false });
    const { container } = renderBlock();
    expect(spin(container)).toBeNull();
  });

  it("suppresses an already-available QR image while loading", () => {
    // Counterpart of the assertion below: the guard is `img && !loading`, so a
    // non-empty image alone must NOT be enough to render it.
    setState({ loading: true, qrcodeImg: QR });
    const { container } = renderBlock();
    expect(img(container)).toBeNull();
    expect(screen.queryByText(HINT_TEXT)).toBeNull();
    expect(spin(container)).toBeTruthy();
  });
});

describe("QrcodeAuthBlock - QR image branch", () => {
  it("renders the base64 image once loading finished", () => {
    setState({ loading: false, qrcodeImg: QR });
    const { container } = renderBlock();
    expect(img(container)?.getAttribute("src")).toBe(
      `data:image/png;base64,${QR}`,
    );
  });

  it("renders the image at the fixed 200x200 box", () => {
    setState({ qrcodeImg: QR });
    const { container } = renderBlock();
    const el = img(container) as HTMLElement;
    expect(el.style.width).toBe("200px");
    expect(el.style.height).toBe("200px");
  });

  it("shows the hint text alongside the image", () => {
    setState({ qrcodeImg: QR });
    renderBlock();
    expect(screen.getByText(HINT_TEXT)).toBeTruthy();
  });

  it("renders neither spinner nor image before the first fetch", () => {
    // Empty-state counterpart: an empty string must not produce an <img>.
    setState({ loading: false, qrcodeImg: "" });
    const { container } = renderBlock();
    expect(img(container)).toBeNull();
    expect(spin(container)).toBeNull();
  });
});

describe("QrcodeAuthBlock - theme-aware hint colour", () => {
  const hintEl = (container: HTMLElement) =>
    Array.from(container.querySelectorAll("div[style]")).find(
      (d) => (d as HTMLElement).style.color.length > 0,
    ) as HTMLElement | undefined;

  it("uses the light-theme colour when isDark is false", () => {
    theme.isDark = false;
    setState({ qrcodeImg: QR });
    const { container } = renderBlock();
    expect(hintEl(container)?.style.color).toBe("rgba(0, 0, 0, 0.45)");
  });

  it("uses the dark-theme colour when isDark is true", () => {
    theme.isDark = true;
    setState({ qrcodeImg: QR });
    const { container } = renderBlock();
    expect(hintEl(container)?.style.color).toBe("rgba(255, 255, 255, 0.45)");
  });

  it("does not apply any hint colour when there is no QR image", () => {
    theme.isDark = true;
    setState({ qrcodeImg: "" });
    const { container } = renderBlock();
    expect(hintEl(container)).toBeUndefined();
  });
});
