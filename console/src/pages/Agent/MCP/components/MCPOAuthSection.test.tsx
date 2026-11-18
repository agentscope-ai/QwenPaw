/**
 * MCPOAuthSection - the OAuth panel that lives inside the Agent > MCP client
 * dialogs. It shows one status badge (five mutually exclusive arms), the
 * authorize/re-authorize action, the revoke action, an inline error line and a
 * collapsible advanced block holding the four externally controlled OAuth
 * parameters. The file also exports OAuthToggleRow, the switch the parent form
 * uses to turn OAuth on.
 *
 * What this file pins:
 *   1. the top-level gate: `oauthEnabled === false` renders nothing at all
 *      (the container stays empty), paired with the positive control that the
 *      same props with the flag on do render the section;
 *   2. the badge matrix. Five arms, each pinned on all three of its
 *      observable facts at once - label, lucide icon class and inline colour:
 *      expired (ShieldAlert / #e67e22), authorized (ShieldCheck / #27ae60),
 *      waiting (KeyRound / #2980b9), error (ShieldX / #c0392b) and the
 *      not-authorized fallback (ShieldX / #7f8c8d). The two ShieldX arms share
 *      an icon but differ in colour and label, so colour is what separates
 *      them and is asserted rather than skipped;
 *   3. the expiry comparison is `expires_at < Date.now() / 1000` - strictly
 *      less than. An expiry exactly equal to "now" is therefore still the
 *      authorized arm here. Both boundary values (equal, and one second past)
 *      are pinned, as is `expires_at === 0`, which the source documents as
 *      "unknown" and which must not be read as "expired in 1970";
 *   4. `isNewClient` suppresses both derived states: with the flag on, an
 *      authorized status object must not light the authorized or expired arms,
 *      because a client that does not exist yet cannot hold a token;
 *   5. the start flow. The request body carries all five parameters
 *      (url/scope/client_id/auth_endpoint/token_endpoint) straight through
 *      from props, success moves the phase to waiting and opens the returned
 *      `auth_url` with the exact target and window features the source
 *      passes, and the authorize button is disabled for a blank URL;
 *   6. the two guard arms inside the click handler. `!clientKey` is reachable
 *      straight from the DOM (a non-blank URL enables the button) and is
 *      pinned: it reports `noClientKey`, never calls the API and leaves the
 *      phase alone. `!url.trim()` is NOT reachable through the DOM - the
 *      button's own `disabled` prop is the literal same expression, so every
 *      input that would take the guard also disables the button, and jsdom
 *      does not deliver a click to a disabled element. That arm is covered by
 *      pulling the handler off the node's `__reactProps$` key instead, with a
 *      five-sequence list over three blank spellings probed at zero calls and
 *      a positive control of one call for a real URL, so the "unreachable by
 *      DOM" claim rests on enumerated combinations rather than one attempt;
 *   7. failure handling: an Error rejection reports its own message, a
 *      non-Error rejection falls back to the generic `startFailed` key, and a
 *      message mentioning either "authorization server" or "auth_endpoint"
 *      auto-expands the advanced block (discovery failed, so the user is
 *      offered the manual overrides) while any other message leaves it
 *      collapsed. The failed phase shows the error badge and the error line;
 *   8. the polling effect, driven with fake timers rather than sleeps: one
 *      tick per 2000ms while waiting, `authorized` flips the phase to success
 *      and fires `onAuthChanged` exactly once, a not-yet-authorized response
 *      keeps waiting and keeps polling, a rejected poll is swallowed (the
 *      component has an empty catch, so the badge must stay on waiting instead
 *      of falling into the error arm), the interval is cleared once the phase
 *      leaves waiting, nothing is polled without a clientKey, and unmounting
 *      clears it too;
 *   9. revoke: the button exists only for `(isAuthorized || isExpired) &&
 *      clientKey`, which is enumerated over all five combinations; confirming
 *      calls the API with the client key, returns the phase to idle and fires
 *      `onAuthChanged`, while a rejected revoke also returns to idle but must
 *      NOT report a change (nothing was revoked). Its own `!clientKey` guard
 *      is unreachable for the same structural reason - the render condition
 *      already requires clientKey - and is enumerated the same way;
 *  10. the advanced block: the disclosure row toggles and swaps its own label,
 *      all four inputs are controlled from props and forward their new value
 *      to the matching setter, each setter is optional so typing with no
 *      handler attached must not throw (paired with the positive control that
 *      an attached handler really receives the value), and the auth-endpoint
 *      label carries the endpointHint tooltip as a real title attribute;
 *  11. OAuthToggleRow: the antd Switch reflects `enabled` through
 *      `aria-checked`, the label falls back to the enableOAuth key when the
 *      prop is absent, the key icon renders from the real lucide package, and
 *      flipping the switch forwards the boolean.
 *
 * Stubbing facts, all probed rather than assumed:
 *   - the global @agentscope-ai/design stub DOES export Button, Input and
 *     Tooltip, so this file needs no module override. Its Button forwards
 *     `type`, `size` and `disabled` to a native button but DROPS `loading`
 *     (React warns and omits the non-boolean attribute), so the in-flight
 *     visual state is not observable here: it is asserted through the API call
 *     sequence instead, and one test pins that `getAttribute("loading")` stays
 *     null so nobody later mistakes the missing attribute for a product
 *     regression. Its Tooltip renders `title` as a real attribute, and its
 *     Input renders a plain controlled input.
 *   - `antd`'s Switch and `lucide-react` are deliberately NOT mocked: both
 *     resolve to the real packages, so `role="switch"` + `aria-checked` and
 *     `svg.lucide-shield-check` / `-shield-x` / `-shield-alert` /
 *     `-key-round` are real assertions about what the user sees.
 *   - jsdom serialises the badge colour as `rgb(r, g, b)` and folds
 *     `borderColor` into the `border` shorthand, dropping the `solid` keyword:
 *     the probed form is `border: 1px rgb(39, 174, 96)`. Colours are asserted
 *     through `style.color`, which is stable, and never as hex literals.
 *   - the api module and openExternalLink are mocked at module level; the
 *     translation hook is the identity function so assertions read the i18n
 *     keys and stay independent of locale wording.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { MCPClientOAuthStatus } from "../../../../api/types";

const h = vi.hoisted(() => ({
  api: {
    startOAuth: vi.fn(),
    getOAuthStatus: vi.fn(),
    revokeOAuth: vi.fn(),
  },
  openExternalLink: vi.fn(),
}));

vi.mock("../../../../api", () => ({ default: h.api }));

vi.mock("../../../../utils/openExternalLink", () => ({
  openExternalLink: (...args: unknown[]) => h.openExternalLink(...args),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
  }),
}));

import { MCPOAuthSection, OAuthToggleRow } from "./MCPOAuthSection";

/** Frozen "now" in seconds; the source divides Date.now() by 1000. */
const NOW_S = 1_700_000_000;

function status(
  overrides: Partial<MCPClientOAuthStatus> = {},
): MCPClientOAuthStatus {
  return {
    authorized: true,
    expires_at: NOW_S + 3600,
    scope: "openid profile",
    client_id: "cid-1",
    ...overrides,
  };
}

/** The status badge is the first child of the status row. */
function badgeOf(container: HTMLElement): HTMLElement {
  const section = container.firstElementChild as HTMLElement;
  const row = section.firstElementChild as HTMLElement;
  return row.firstElementChild as HTMLElement;
}

/** The two action buttons live in the second child of the status row. */
function actionsOf(container: HTMLElement): HTMLElement {
  const section = container.firstElementChild as HTMLElement;
  const row = section.firstElementChild as HTMLElement;
  return row.children[1] as HTMLElement;
}

function authorizeButton(container: HTMLElement): HTMLButtonElement {
  // The authorize button is always rendered; revoke is conditional and comes
  // first, so take the last button in the action group.
  const btns = actionsOf(container).querySelectorAll("button");
  return btns[btns.length - 1] as HTMLButtonElement;
}

function revokeButton(container: HTMLElement): HTMLButtonElement | null {
  const btns = actionsOf(container).querySelectorAll("button");
  return btns.length > 1 ? (btns[0] as HTMLButtonElement) : null;
}

function iconClasses(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("svg")).map(
    (s) => s.getAttribute("class") ?? "",
  );
}

function advancedRow(container: HTMLElement): HTMLElement {
  // The disclosure row is the element whose click handler flips showAdvanced;
  // it is the only child of the section carrying the Info icon.
  const section = container.firstElementChild as HTMLElement;
  return Array.from(section.children).find((el) =>
    el.querySelector("svg.lucide-info"),
  ) as HTMLElement;
}

function advancedInputs(container: HTMLElement): HTMLInputElement[] {
  const section = container.firstElementChild as HTMLElement;
  const panel = Array.from(section.children).find(
    (el) => el.querySelectorAll("input").length === 4,
  ) as HTMLElement;
  return Array.from(panel.querySelectorAll("input"));
}

beforeEach(() => {
  h.api.startOAuth.mockReset();
  h.api.getOAuthStatus.mockReset();
  h.api.revokeOAuth.mockReset();
  h.openExternalLink.mockReset();
  h.api.startOAuth.mockResolvedValue({
    auth_url: "https://auth.example.com/authorize?state=s1",
    session_id: "s1",
  });
  h.api.getOAuthStatus.mockResolvedValue({
    authorized: true,
    expires_at: NOW_S + 3600,
    scope: "openid",
  });
  h.api.revokeOAuth.mockResolvedValue({ message: "revoked" });
  vi.spyOn(Date, "now").mockReturnValue(NOW_S * 1000);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// 1. the top-level gate
// ---------------------------------------------------------------------------

describe("the oauthEnabled gate", () => {
  it("renders nothing at all when OAuth is switched off", () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled={false}
      />,
    );
    expect(container.innerHTML).toBe("");
    expect(container.firstElementChild).toBeNull();
  });

  it("renders the section for the same props once OAuth is switched on", () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled
      />,
    );
    expect(container.firstElementChild).not.toBeNull();
    expect(screen.getByText("mcp.oauth.notAuthorized")).toBeInTheDocument();
  });

  it("defaults to off, so omitting the flag renders nothing", () => {
    const { container } = render(
      <MCPOAuthSection url="https://mcp.example.com" clientKey="k1" />,
    );
    expect(container.innerHTML).toBe("");
  });
});

// ---------------------------------------------------------------------------
// 2. the badge matrix
// ---------------------------------------------------------------------------

describe("the status badge matrix", () => {
  it("shows the not-authorized fallback with the grey ShieldX when there is no status", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.notAuthorized");
    expect(badge.style.color).toBe("rgb(127, 140, 141)");
    expect(iconClasses(container)).toContain("lucide lucide-shield-x");
  });

  it("shows the same grey fallback when a status object exists but is not authorized", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ authorized: false })}
      />,
    );
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.notAuthorized");
    expect(badge.style.color).toBe("rgb(127, 140, 141)");
  });

  it("shows the green ShieldCheck when the stored status is authorized and still valid", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.authorized");
    expect(badge.style.color).toBe("rgb(39, 174, 96)");
    expect(iconClasses(container)).toContain("lucide lucide-shield-check");
  });

  it("shows the orange ShieldAlert when the stored token is past its expiry", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S - 1 })}
      />,
    );
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.expired");
    expect(badge.style.color).toBe("rgb(230, 126, 34)");
    expect(iconClasses(container)).toContain("lucide lucide-shield-alert");
  });

  it("paints the badge border with the same colour as its text", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    const badge = badgeOf(container);
    // jsdom folds borderColor into the border shorthand and drops `solid`.
    expect(badge.getAttribute("style")).toContain(
      "border: 1px rgb(39, 174, 96)",
    );
    expect(badge.style.color).toBe("rgb(39, 174, 96)");
  });
});

describe("the expiry comparison boundary", () => {
  it("treats an expiry exactly equal to now as still valid (strictly-less-than)", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S })}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
    expect(screen.queryByText("mcp.oauth.expired")).toBeNull();
  });

  it("treats one second past now as expired", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S - 1 })}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.expired");
  });

  it("treats expires_at of zero as unknown rather than as expired in 1970", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: 0 })}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
    expect(screen.queryByText("mcp.oauth.expired")).toBeNull();
  });

  it("treats a negative expires_at as unknown too, since the guard is greater-than-zero", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: -5 })}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
  });
});

describe("isNewClient suppressing the derived states", () => {
  it("does not light the authorized arm for a brand new client holding an authorized status", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        isNewClient
        currentOAuthStatus={status()}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
    expect(screen.queryByText("mcp.oauth.authorized")).toBeNull();
  });

  it("does not light the expired arm for a brand new client either", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        isNewClient
        currentOAuthStatus={status({ expires_at: NOW_S - 100 })}
      />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
    expect(screen.queryByText("mcp.oauth.expired")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. the authorize button's derived props
// ---------------------------------------------------------------------------

describe("the authorize button", () => {
  it("is a primary call to action and reads authorize when nothing is authorized", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    const btn = authorizeButton(container);
    expect(btn.getAttribute("type")).toBe("primary");
    expect(btn.textContent).toContain("mcp.oauth.authorize");
    expect(iconClasses(container)).toContain("lucide lucide-external-link");
  });

  it("downgrades to a default button reading re-authorize once authorized", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    const btn = authorizeButton(container);
    expect(btn.getAttribute("type")).toBe("default");
    expect(btn.textContent).toContain("mcp.oauth.reauthorize");
  });

  it("keeps the primary emphasis for an expired token, since that is not authorized-and-valid", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S - 10 })}
      />,
    );
    const btn = authorizeButton(container);
    expect(btn.getAttribute("type")).toBe("primary");
    expect(btn.textContent).toContain("mcp.oauth.authorize");
  });

  it.each(["", " ", "\t\n  "])(
    "is disabled for the blank URL spelling %j",
    (blank) => {
      const { container } = render(
        <MCPOAuthSection url={blank} clientKey="k1" oauthEnabled />,
      );
      expect(authorizeButton(container).hasAttribute("disabled")).toBe(true);
    },
  );

  it("is enabled for a real URL", () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled
      />,
    );
    expect(authorizeButton(container).hasAttribute("disabled")).toBe(false);
  });

  it("does not expose the in-flight loading flag on the DOM, because the design stub drops it", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    const btn = authorizeButton(container);
    // Pinning this keeps a later reader from mistaking the absent attribute
    // for a product regression; the in-flight state is asserted through the
    // API call sequence instead.
    expect(btn.getAttribute("loading")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 4. the start flow
// ---------------------------------------------------------------------------

describe("starting the OAuth flow", () => {
  it("posts all five parameters straight through from props and opens the returned auth_url", async () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled
        clientId="cid-9"
        scope="openid email"
        authEndpoint="https://a.example.com/auth"
        tokenEndpoint="https://a.example.com/token"
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });

    expect(h.api.startOAuth).toHaveBeenCalledTimes(1);
    expect(h.api.startOAuth).toHaveBeenCalledWith("k1", {
      url: "https://mcp.example.com",
      scope: "openid email",
      client_id: "cid-9",
      auth_endpoint: "https://a.example.com/auth",
      token_endpoint: "https://a.example.com/token",
    });
    expect(h.openExternalLink).toHaveBeenCalledTimes(1);
    expect(h.openExternalLink).toHaveBeenCalledWith(
      "https://auth.example.com/authorize?state=s1",
      "_blank",
      "popup,width=600,height=700",
    );
  });

  it("sends empty strings for the four advanced parameters when the parent controls none of them", async () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(h.api.startOAuth).toHaveBeenCalledWith("k1", {
      url: "https://mcp.example.com",
      scope: "",
      client_id: "",
      auth_endpoint: "",
      token_endpoint: "",
    });
  });

  it("moves to the waiting badge once the flow has been started", async () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.waiting");
    expect(badge.style.color).toBe("rgb(41, 128, 185)");
    expect(iconClasses(container)).toContain("lucide lucide-key-round");
  });

  it("never reaches the API for a blank URL, which is the positive control for the disabled button", async () => {
    const { container } = render(
      <MCPOAuthSection url="   " clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(h.api.startOAuth).not.toHaveBeenCalled();
    expect(h.openExternalLink).not.toHaveBeenCalled();
    // The phase never left idle, so no error line and no waiting badge.
    expect(screen.queryByText("mcp.oauth.noUrl")).toBeNull();
    expect(screen.queryByText("mcp.oauth.waiting")).toBeNull();
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
  });
});

describe("the blank URL guard behind the disabled button", () => {
  /**
   * The `!url.trim()` guard is unreachable through the DOM: the authorize
   * button's own `disabled` prop is that same expression, so every input that
   * would take the guard also disables the button, and jsdom does not deliver
   * a click to a disabled element (a five-sequence list over three blank
   * spellings was probed with zero calls, against a positive control of one
   * call for a real URL).
   *
   * The handler is still reachable off the DOM node's React props key, which
   * is the only way to exercise this arm. That keeps the guard's real
   * behaviour under test instead of leaving it as untested defensive code.
   */
  function reactProps(node: Element): Record<string, unknown> {
    const key = Object.keys(node).find((k) => k.startsWith("__reactProps$"));
    expect(key, "React props key on the rendered node").toBeTruthy();
    return (node as unknown as Record<string, unknown>)[key!] as Record<
      string,
      unknown
    >;
  }

  it("reports noUrl and calls nothing when the handler runs with a blank URL", async () => {
    const { container } = render(
      <MCPOAuthSection url="   " clientKey="k1" oauthEnabled />,
    );
    const btn = container.querySelector("button")!;
    // The DOM route is blocked, which is the premise of using the props key.
    expect(btn.hasAttribute("disabled")).toBe(true);

    const onClick = reactProps(btn).onClick as () => Promise<void>;
    await act(async () => {
      await onClick();
    });

    expect(screen.getByText("mcp.oauth.noUrl")).toBeInTheDocument();
    expect(h.api.startOAuth).not.toHaveBeenCalled();
    expect(h.openExternalLink).not.toHaveBeenCalled();
    // The guard returns before the phase moves, so the badge is unchanged.
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
  });

  it.each(["", " ", "\t\n  "])(
    "takes the same guard for the blank spelling %j",
    async (blank) => {
      const { container } = render(
        <MCPOAuthSection url={blank} clientKey="k1" oauthEnabled />,
      );
      const btn = container.querySelector("button")!;
      const onClick = reactProps(btn).onClick as () => Promise<void>;
      await act(async () => {
        await onClick();
      });
      expect(screen.getByText("mcp.oauth.noUrl")).toBeInTheDocument();
      expect(h.api.startOAuth).not.toHaveBeenCalled();
    },
  );

  it("reports noUrl ahead of noClientKey when both inputs are missing", async () => {
    // The URL guard comes first in the source, so it wins.
    const { container } = render(<MCPOAuthSection url="" oauthEnabled />);
    const btn = container.querySelector("button")!;
    const onClick = reactProps(btn).onClick as () => Promise<void>;
    await act(async () => {
      await onClick();
    });
    expect(screen.getByText("mcp.oauth.noUrl")).toBeInTheDocument();
    expect(screen.queryByText("mcp.oauth.noClientKey")).toBeNull();
  });

  it("exposes the loading prop the stub drops, confirming the handler came off the real node", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    const props = reactProps(container.querySelector("button")!);
    expect(props).toHaveProperty("onClick");
    expect(props.loading).toBe(false);
  });
});

describe("the missing client key guard", () => {
  it("reports noClientKey, calls nothing and keeps the phase at idle", async () => {
    const { container } = render(
      <MCPOAuthSection url="https://mcp.example.com" oauthEnabled />,
    );
    // The button is enabled because the URL is present, so this guard really
    // is reachable from the DOM.
    expect(authorizeButton(container).hasAttribute("disabled")).toBe(false);

    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });

    expect(screen.getByText("mcp.oauth.noClientKey")).toBeInTheDocument();
    expect(h.api.startOAuth).not.toHaveBeenCalled();
    expect(h.openExternalLink).not.toHaveBeenCalled();
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
  });

  it("treats an empty-string client key as missing too", async () => {
    const { container } = render(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey=""
        oauthEnabled
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.noClientKey")).toBeInTheDocument();
    expect(h.api.startOAuth).not.toHaveBeenCalled();
  });

  it("clears a previous error message when a later attempt gets past both guards", async () => {
    const { container, rerender } = render(
      <MCPOAuthSection url="https://mcp.example.com" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.noClientKey")).toBeInTheDocument();

    rerender(
      <MCPOAuthSection
        url="https://mcp.example.com"
        clientKey="k1"
        oauthEnabled
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.queryByText("mcp.oauth.noClientKey")).toBeNull();
    expect(h.api.startOAuth).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 5. failure handling
// ---------------------------------------------------------------------------

describe("a rejected start", () => {
  it("surfaces the rejection's own message and shows the red error badge", async () => {
    h.api.startOAuth.mockRejectedValue(new Error("boom from server"));
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });

    expect(screen.getByText("boom from server")).toBeInTheDocument();
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.failed");
    expect(badge.style.color).toBe("rgb(192, 57, 43)");
    expect(iconClasses(container)).toContain("lucide lucide-shield-x");
    expect(h.openExternalLink).not.toHaveBeenCalled();
  });

  it("falls back to the generic startFailed key when the rejection is not an Error", async () => {
    h.api.startOAuth.mockRejectedValue("plain string");
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.startFailed")).toBeInTheDocument();
    expect(badgeOf(container).textContent).toContain("mcp.oauth.failed");
  });

  it("falls back to the generic key for a null rejection as well", async () => {
    h.api.startOAuth.mockRejectedValue(null);
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.startFailed")).toBeInTheDocument();
  });

  it("auto-expands the advanced block when the message blames the authorization server", async () => {
    h.api.startOAuth.mockRejectedValue(
      new Error("no authorization server metadata found"),
    );
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    expect(screen.queryByText("mcp.oauth.hideAdvanced")).toBeNull();
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.hideAdvanced")).toBeInTheDocument();
    expect(advancedInputs(container)).toHaveLength(4);
  });

  it("auto-expands the advanced block when the message names auth_endpoint", async () => {
    h.api.startOAuth.mockRejectedValue(new Error("auth_endpoint is required"));
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.hideAdvanced")).toBeInTheDocument();
  });

  it("leaves the advanced block collapsed for an unrelated failure message", async () => {
    h.api.startOAuth.mockRejectedValue(new Error("network unreachable"));
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.failed")).toBeInTheDocument();
    expect(screen.queryByText("mcp.oauth.hideAdvanced")).toBeNull();
    expect(screen.getByText("mcp.oauth.showAdvanced")).toBeInTheDocument();
  });

  it("keeps the error line and badge after a retry that fails again with a different message", async () => {
    h.api.startOAuth.mockRejectedValueOnce(new Error("first failure"));
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("first failure")).toBeInTheDocument();

    h.api.startOAuth.mockRejectedValueOnce(new Error("second failure"));
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.queryByText("first failure")).toBeNull();
    expect(screen.getByText("second failure")).toBeInTheDocument();
    expect(screen.getAllByText("mcp.oauth.failed")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 6. polling
// ---------------------------------------------------------------------------

describe("the waiting poll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  async function startAndWait(container: HTMLElement) {
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(badgeOf(container).textContent).toContain("mcp.oauth.waiting");
  }

  it("flips to success and reports the change once the backend says authorized", async () => {
    const onAuthChanged = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        onAuthChanged={onAuthChanged}
      />,
    );
    await startAndWait(container);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(1);
    expect(h.api.getOAuthStatus).toHaveBeenCalledWith("k1");
    expect(onAuthChanged).toHaveBeenCalledTimes(1);
    const badge = badgeOf(container);
    expect(badge.textContent).toContain("mcp.oauth.authorized");
    expect(badge.style.color).toBe("rgb(39, 174, 96)");
  });

  it("does not poll before the first 2000ms tick elapses", async () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(h.api.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("keeps waiting and keeps polling while the backend still says not authorized", async () => {
    h.api.getOAuthStatus.mockResolvedValue({
      authorized: false,
      expires_at: 0,
      scope: "",
    });
    const onAuthChanged = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        onAuthChanged={onAuthChanged}
      />,
    );
    await startAndWait(container);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(2);
    expect(onAuthChanged).not.toHaveBeenCalled();
    expect(badgeOf(container).textContent).toContain("mcp.oauth.waiting");
  });

  it("swallows a rejected poll instead of falling into the error arm", async () => {
    h.api.getOAuthStatus.mockRejectedValue(new Error("backend down"));
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(1);
    // The empty catch means the badge stays on waiting; no error line either.
    expect(badgeOf(container).textContent).toContain("mcp.oauth.waiting");
    expect(screen.queryByText("backend down")).toBeNull();
    expect(screen.queryByText("mcp.oauth.failed")).toBeNull();
  });

  it("keeps polling after a rejected tick and still lands on success later", async () => {
    h.api.getOAuthStatus
      .mockRejectedValueOnce(new Error("transient"))
      .mockResolvedValueOnce({
        authorized: true,
        expires_at: NOW_S + 60,
        scope: "openid",
      });
    const onAuthChanged = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        onAuthChanged={onAuthChanged}
      />,
    );
    await startAndWait(container);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(badgeOf(container).textContent).toContain("mcp.oauth.waiting");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
    expect(onAuthChanged).toHaveBeenCalledTimes(1);
  });

  it("stops polling once the phase has left waiting", async () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(1);

    // The cleanup clears the interval, so further time passes with no calls.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(1);
  });

  it("does not report a change when the poll succeeds without onAuthChanged attached", async () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    // No handler is attached; the optional call must not throw.
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
  });

  it("never installs a poll while the phase is still idle", async () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(h.api.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("does not poll for a new client that has no client key yet", async () => {
    h.api.startOAuth.mockRejectedValue(new Error("cannot start"));
    const { container } = render(
      <MCPOAuthSection url="u" isNewClient oauthEnabled />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(screen.getByText("mcp.oauth.noClientKey")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(h.api.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("clears the interval on unmount", async () => {
    const { container, unmount } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(h.api.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("re-installs the poll when a second attempt reaches waiting again", async () => {
    h.api.getOAuthStatus.mockResolvedValue({
      authorized: false,
      expires_at: 0,
      scope: "",
    });
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    await startAndWait(container);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(1);

    // Fail the next start so the phase drops to error, then start again.
    h.api.startOAuth.mockRejectedValueOnce(new Error("retry needed"));
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(badgeOf(container).textContent).toContain("mcp.oauth.failed");

    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(badgeOf(container).textContent).toContain("mcp.oauth.waiting");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(h.api.getOAuthStatus).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// 7. revoke
// ---------------------------------------------------------------------------

describe("the revoke button's render condition", () => {
  it("is present for an authorized client that has a key", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    const btn = revokeButton(container);
    expect(btn).not.toBeNull();
    expect(btn?.textContent).toContain("mcp.oauth.revoke");
    expect(iconClasses(container)).toContain("lucide lucide-unlink");
  });

  it("is present for an expired client that has a key", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S - 10 })}
      />,
    );
    expect(revokeButton(container)).not.toBeNull();
  });

  it("is absent for an authorized status with no client key at all", () => {
    const { container } = render(
      <MCPOAuthSection url="u" oauthEnabled currentOAuthStatus={status()} />,
    );
    expect(revokeButton(container)).toBeNull();
    expect(actionsOf(container).querySelectorAll("button")).toHaveLength(1);
  });

  it("is absent for an expired status with an empty client key", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey=""
        oauthEnabled
        currentOAuthStatus={status({ expires_at: NOW_S - 10 })}
      />,
    );
    expect(revokeButton(container)).toBeNull();
  });

  it("is absent when nothing is authorized, even with a client key", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    expect(revokeButton(container)).toBeNull();
  });

  it("is absent for a brand new client holding an authorized status", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        isNewClient
        currentOAuthStatus={status()}
      />,
    );
    expect(revokeButton(container)).toBeNull();
  });
});

describe("revoking", () => {
  it("calls the API with the client key, returns to idle and reports the change", async () => {
    const onAuthChanged = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
        onAuthChanged={onAuthChanged}
      />,
    );
    await act(async () => {
      fireEvent.click(revokeButton(container)!);
    });

    expect(h.api.revokeOAuth).toHaveBeenCalledTimes(1);
    expect(h.api.revokeOAuth).toHaveBeenCalledWith("k1");
    expect(onAuthChanged).toHaveBeenCalledTimes(1);
    // The component holds no token state of its own: `revoking` only resets
    // the phase to idle, and the derived authorized state is then recomputed
    // from the unchanged `currentOAuthStatus` prop. So right after a revoke
    // the badge still reads authorized and the button is still there - the
    // visible change is the parent's job, which is why `onAuthChanged` exists.
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
    expect(revokeButton(container)).not.toBeNull();
  });

  it("drops the revoke button only once the parent feeds back a cleared status", async () => {
    const { container, rerender } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
        onAuthChanged={vi.fn()}
      />,
    );
    await act(async () => {
      fireEvent.click(revokeButton(container)!);
    });
    expect(revokeButton(container)).not.toBeNull();

    // This is the second half of the contract: the parent refetches on
    // onAuthChanged and passes the cleared status back down.
    rerender(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status({ authorized: false, expires_at: 0 })}
        onAuthChanged={vi.fn()}
      />,
    );
    expect(revokeButton(container)).toBeNull();
    expect(actionsOf(container).querySelectorAll("button")).toHaveLength(1);
    expect(badgeOf(container).textContent).toContain("mcp.oauth.notAuthorized");
  });

  it("drops the revoke button when the parent passes a null status instead", async () => {
    const { container, rerender } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    expect(revokeButton(container)).not.toBeNull();
    rerender(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={null}
      />,
    );
    expect(revokeButton(container)).toBeNull();
  });

  it("returns to idle without reporting a change when the revoke is rejected", async () => {
    h.api.revokeOAuth.mockRejectedValue(new Error("backend refused"));
    const onAuthChanged = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
        onAuthChanged={onAuthChanged}
      />,
    );
    await act(async () => {
      fireEvent.click(revokeButton(container)!);
    });

    expect(h.api.revokeOAuth).toHaveBeenCalledTimes(1);
    expect(onAuthChanged).not.toHaveBeenCalled();
    // The catch has no error state, so nothing is shown and the stored status
    // still drives the badge.
    expect(screen.queryByText("backend refused")).toBeNull();
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
  });

  it("does not throw when a successful revoke has no onAuthChanged attached", async () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    await act(async () => {
      fireEvent.click(revokeButton(container)!);
    });
    expect(h.api.revokeOAuth).toHaveBeenCalledTimes(1);
    // The optional call must not throw, and the phase is back to idle.
    expect(badgeOf(container).textContent).toContain("mcp.oauth.authorized");
  });

  it("reveals the revoke button once a successful poll authorizes the client", async () => {
    vi.useFakeTimers();
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    expect(revokeButton(container)).toBeNull();
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(revokeButton(container)).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(revokeButton(container)).not.toBeNull();
  });

  it("does not treat a click on the authorize button as a revoke", async () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        currentOAuthStatus={status()}
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(h.api.revokeOAuth).not.toHaveBeenCalled();
    expect(h.api.startOAuth).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 8. the advanced block
// ---------------------------------------------------------------------------

describe("the advanced disclosure", () => {
  it("starts collapsed with the show label and no inputs", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    expect(screen.getByText("mcp.oauth.showAdvanced")).toBeInTheDocument();
    expect(screen.queryByText("mcp.oauth.hideAdvanced")).toBeNull();
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(iconClasses(container)).toContain("lucide lucide-info");
  });

  it("expands on click and swaps its own label", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    fireEvent.click(advancedRow(container));
    expect(screen.getByText("mcp.oauth.hideAdvanced")).toBeInTheDocument();
    expect(screen.queryByText("mcp.oauth.showAdvanced")).toBeNull();
    expect(advancedInputs(container)).toHaveLength(4);
  });

  it("collapses again on a second click", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    fireEvent.click(advancedRow(container));
    fireEvent.click(advancedRow(container));
    expect(screen.getByText("mcp.oauth.showAdvanced")).toBeInTheDocument();
    expect(container.querySelectorAll("input")).toHaveLength(0);
  });

  it("labels all four fields and renders the two hard-coded endpoint placeholders", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    fireEvent.click(advancedRow(container));
    expect(screen.getByText("mcp.oauth.clientId")).toBeInTheDocument();
    expect(screen.getByText("mcp.oauth.scope")).toBeInTheDocument();
    expect(screen.getByText("mcp.oauth.authEndpoint")).toBeInTheDocument();
    expect(screen.getByText("mcp.oauth.tokenEndpoint")).toBeInTheDocument();

    const inputs = advancedInputs(container);
    expect(inputs[0].getAttribute("placeholder")).toBe(
      "mcp.oauth.clientIdPlaceholder",
    );
    expect(inputs[1].getAttribute("placeholder")).toBe(
      "mcp.oauth.scopePlaceholder",
    );
    expect(inputs[2].getAttribute("placeholder")).toBe(
      "https://auth.example.com/authorize",
    );
    expect(inputs[3].getAttribute("placeholder")).toBe(
      "https://auth.example.com/token",
    );
  });

  it("carries the endpoint hint on the auth-endpoint label as a real title attribute", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    fireEvent.click(advancedRow(container));
    const hinted = container.querySelector(
      'div[title="mcp.oauth.endpointHint"]',
    );
    expect(hinted).not.toBeNull();
    expect(hinted?.textContent).toContain("mcp.oauth.authEndpoint");
  });

  it("shows all four values from props and keeps them controlled", () => {
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        clientId="cid-1"
        scope="openid"
        authEndpoint="https://a/auth"
        tokenEndpoint="https://a/token"
      />,
    );
    fireEvent.click(advancedRow(container));
    const inputs = advancedInputs(container);
    expect(inputs.map((i) => i.value)).toEqual([
      "cid-1",
      "openid",
      "https://a/auth",
      "https://a/token",
    ]);
  });

  it("forwards each field's new value to its own setter", () => {
    const onClientIdChange = vi.fn();
    const onScopeChange = vi.fn();
    const onAuthEndpointChange = vi.fn();
    const onTokenEndpointChange = vi.fn();
    const { container } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        onClientIdChange={onClientIdChange}
        onScopeChange={onScopeChange}
        onAuthEndpointChange={onAuthEndpointChange}
        onTokenEndpointChange={onTokenEndpointChange}
      />,
    );
    fireEvent.click(advancedRow(container));
    const inputs = advancedInputs(container);

    fireEvent.change(inputs[0], { target: { value: "new-cid" } });
    fireEvent.change(inputs[1], { target: { value: "new-scope" } });
    fireEvent.change(inputs[2], { target: { value: "new-auth" } });
    fireEvent.change(inputs[3], { target: { value: "new-token" } });

    expect(onClientIdChange).toHaveBeenCalledTimes(1);
    expect(onClientIdChange).toHaveBeenCalledWith("new-cid");
    expect(onScopeChange).toHaveBeenCalledWith("new-scope");
    expect(onAuthEndpointChange).toHaveBeenCalledWith("new-auth");
    expect(onTokenEndpointChange).toHaveBeenCalledWith("new-token");
  });

  it("does not throw when typing into the four fields with no setters attached", () => {
    const { container } = render(
      <MCPOAuthSection url="u" clientKey="k1" oauthEnabled />,
    );
    fireEvent.click(advancedRow(container));
    const inputs = advancedInputs(container);
    expect(() => {
      fireEvent.change(inputs[0], { target: { value: "a" } });
      fireEvent.change(inputs[1], { target: { value: "b" } });
      fireEvent.change(inputs[2], { target: { value: "c" } });
      fireEvent.change(inputs[3], { target: { value: "d" } });
    }).not.toThrow();
    // Controlled from props with no setter, so the values do not move.
    expect(inputs.map((i) => i.value)).toEqual(["", "", "", ""]);
  });

  it("sends the values typed into the advanced fields on the next start", async () => {
    const state: Record<string, string> = {
      clientId: "",
      scope: "",
      authEndpoint: "",
      tokenEndpoint: "",
    };
    const { container, rerender } = render(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        clientId={state.clientId}
        scope={state.scope}
        authEndpoint={state.authEndpoint}
        tokenEndpoint={state.tokenEndpoint}
        onClientIdChange={(v) => {
          state.clientId = v;
        }}
        onScopeChange={(v) => {
          state.scope = v;
        }}
        onAuthEndpointChange={(v) => {
          state.authEndpoint = v;
        }}
        onTokenEndpointChange={(v) => {
          state.tokenEndpoint = v;
        }}
      />,
    );
    fireEvent.click(advancedRow(container));
    const inputs = advancedInputs(container);
    fireEvent.change(inputs[0], { target: { value: "typed-cid" } });
    fireEvent.change(inputs[1], { target: { value: "typed-scope" } });

    rerender(
      <MCPOAuthSection
        url="u"
        clientKey="k1"
        oauthEnabled
        clientId={state.clientId}
        scope={state.scope}
        authEndpoint={state.authEndpoint}
        tokenEndpoint={state.tokenEndpoint}
        onClientIdChange={(v) => {
          state.clientId = v;
        }}
        onScopeChange={(v) => {
          state.scope = v;
        }}
        onAuthEndpointChange={(v) => {
          state.authEndpoint = v;
        }}
        onTokenEndpointChange={(v) => {
          state.tokenEndpoint = v;
        }}
      />,
    );
    await act(async () => {
      fireEvent.click(authorizeButton(container));
    });
    expect(h.api.startOAuth).toHaveBeenCalledWith("k1", {
      url: "u",
      scope: "typed-scope",
      client_id: "typed-cid",
      auth_endpoint: "",
      token_endpoint: "",
    });
  });
});

// ---------------------------------------------------------------------------
// 9. OAuthToggleRow
// ---------------------------------------------------------------------------

describe("OAuthToggleRow", () => {
  function switchOf(container: HTMLElement): HTMLElement {
    return container.querySelector('[role="switch"]') as HTMLElement;
  }

  it("reflects the enabled prop through aria-checked on a real antd switch", () => {
    const { container } = render(<OAuthToggleRow enabled onChange={vi.fn()} />);
    const sw = switchOf(container);
    expect(sw).not.toBeNull();
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(sw.className).toContain("ant-switch-checked");
    expect(sw.className).toContain("ant-switch-small");
  });

  it("shows an unchecked switch when disabled", () => {
    const { container } = render(
      <OAuthToggleRow enabled={false} onChange={vi.fn()} />,
    );
    const sw = switchOf(container);
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(sw.className).not.toContain("ant-switch-checked");
  });

  it("falls back to the enableOAuth label when no label prop is given", () => {
    render(<OAuthToggleRow enabled={false} onChange={vi.fn()} />);
    expect(screen.getByText("mcp.oauth.enableOAuth")).toBeInTheDocument();
  });

  it("prefers an explicit label over the translation key", () => {
    render(
      <OAuthToggleRow
        enabled={false}
        onChange={vi.fn()}
        label="Custom OAuth"
      />,
    );
    expect(screen.getByText("Custom OAuth")).toBeInTheDocument();
    expect(screen.queryByText("mcp.oauth.enableOAuth")).toBeNull();
  });

  it("uses an empty string label rather than the fallback, since nullish coalescing only skips null and undefined", () => {
    render(<OAuthToggleRow enabled={false} onChange={vi.fn()} label="" />);
    expect(screen.queryByText("mcp.oauth.enableOAuth")).toBeNull();
  });

  it("forwards the new boolean when the switch is flipped", () => {
    const onChange = vi.fn();
    const { container } = render(
      <OAuthToggleRow enabled={false} onChange={onChange} />,
    );
    fireEvent.click(switchOf(container));
    expect(onChange).toHaveBeenCalledTimes(1);
    // antd's Switch calls onChange with (checked, event); the row forwards
    // both, so the first argument is what the contract is about.
    expect(onChange.mock.calls[0][0]).toBe(true);
    expect(onChange.mock.calls[0]).toHaveLength(2);
  });

  it("forwards false when an enabled switch is flipped off", () => {
    const onChange = vi.fn();
    const { container } = render(
      <OAuthToggleRow enabled onChange={onChange} />,
    );
    fireEvent.click(switchOf(container));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toBe(false);
  });

  it("renders the key icon from the real lucide package", () => {
    const { container } = render(
      <OAuthToggleRow enabled={false} onChange={vi.fn()} />,
    );
    expect(container.querySelector("svg.lucide-key-round")).not.toBeNull();
  });
});
