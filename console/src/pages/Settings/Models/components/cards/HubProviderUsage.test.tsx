/**
 * HubProviderUsage - the monthly token budget widget shown inside the
 * hub-managed provider card (Settings > Models).
 *
 * What this file pins:
 *   1. the data contract: one GET of "me/usage" on mount, the refresh button
 *      re-runs exactly the same loader, and a successful reload clears a
 *      previous error;
 *   2. the 30s polling contract: one interval is scheduled with a 30000ms
 *      period, it re-polls, the loader identity is stable so a re-render
 *      does not re-schedule it, and unmounting clears it (no post-unmount
 *      request);
 *   3. the blocked predicate, which has two independent triggers
 *      (member.remaining === 0 OR usage.organization_blocked) and drives
 *      both the warning line and the progress bar's exception styling;
 *   4. the percentage computation, including its three arms (a real limit,
 *      an explicit zero limit, and a null/unlimited limit) and the 100% cap;
 *   5. the conditional rows: remaining is hidden only for an explicit null,
 *      reserved is hidden for 0, the unlimited label replaces the number;
 *   6. locale-sensitive number formatting via toLocaleString(i18n.language);
 *   7. the error surface: role="alert" plus the real governanceErrorMessage
 *      mapping (known key -> i18n key, unknown detail -> passthrough), and
 *      the loading line being suppressed while an error is present;
 *   8. the pre-data loading state and the CSS-module class contract.
 *
 * antd's Progress and Button are used directly by the product (they are not
 * routed through the @agentscope-ai/design stub), so they are rendered for
 * real: the bar is asserted through its role="progressbar" element, its
 * aria-valuenow, the status class and the inline stroke-colour variable.
 * governanceErrorMessage is deliberately left unmocked - it is a pure module,
 * and mapping error details to i18n keys is part of what this widget does.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const request = vi.hoisted(() => vi.fn());
vi.mock("../../../../../api/modules/hubGovernance", () => ({
  governanceRequest: (...args: unknown[]) => request(...args),
}));

const i18nState = vi.hoisted(() => ({ language: "en" }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: i18nState,
  }),
}));

import HubProviderUsage from "./HubProviderUsage";
import styles from "./HubProviderUsage.module.less";

/** A complete BudgetUsage member, so every test states only what it varies. */
function memberOf(overrides: Record<string, unknown> = {}) {
  return {
    subject: "member-1",
    period: "2026-09",
    token_limit: 1000,
    remaining: 500,
    charged: 300,
    actual: 300,
    reserved: 200,
    conservative: 0,
    requests: 7,
    ...overrides,
  };
}

function usageOf(
  memberOverrides: Record<string, unknown> | null = {},
  organizationBlocked = false,
) {
  return {
    member: memberOverrides === null ? null : memberOf(memberOverrides),
    organization_blocked: organizationBlocked,
  };
}

const REFRESH_LABEL = "hub.governance.member.refreshBudget";
const BAR_LABEL = "hub.governance.users.usageBudget";
const ACCENT = "var(--app-accent)";
const DANGER = "var(--app-error-text)";

/** Renders the widget and waits for the first "me/usage" response to land. */
async function renderLoaded(
  payload: unknown = usageOf(),
): Promise<ReturnType<typeof render>> {
  request.mockResolvedValue(payload);
  const view = render(<HubProviderUsage />);
  await screen.findByText("hub.governance.dashboard.monthlyTokens");
  await act(async () => {
    await Promise.resolve();
  });
  return view;
}

function progressBar() {
  return screen.getByRole("progressbar", { name: BAR_LABEL });
}

/** The antd bar paints its status into a class, not into an attribute. */
function progressStatus(): string | null {
  const match = progressBar().className.match(/ant-progress-status-(\w+)/);
  return match ? match[1] : null;
}

function barInner(): HTMLElement {
  const inner = progressBar().querySelector<HTMLElement>(".ant-progress-bg");
  expect(inner).toBeTruthy();
  return inner as HTMLElement;
}

beforeEach(() => {
  request.mockReset();
  i18nState.language = "en";
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("HubProviderUsage - data contract", () => {
  it("fetches me/usage once on mount", async () => {
    await renderLoaded();
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("me/usage");
  });

  it("re-runs the very same loader when the refresh button is clicked", async () => {
    await renderLoaded();
    expect(request).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: REFRESH_LABEL }));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(request.mock.calls[1]).toEqual(["me/usage"]);
  });

  it("shows the loading line before any data has arrived", async () => {
    let release: (value: unknown) => void = () => {};
    request.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    render(<HubProviderUsage />);
    expect(
      screen.getByText("hub.governance.member.loadingBudget"),
    ).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => {
      release(usageOf());
    });
    expect(
      screen.queryByText("hub.governance.member.loadingBudget"),
    ).toBeNull();
  });

  it("clears a previous error once a reload succeeds", async () => {
    request.mockRejectedValueOnce(new Error("Failed to fetch"));
    render(<HubProviderUsage />);
    await screen.findByRole("alert");
    request.mockResolvedValue(usageOf());
    fireEvent.click(screen.getByRole("button", { name: REFRESH_LABEL }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(
      screen.getByText("hub.governance.dashboard.monthlyTokens"),
    ).toBeTruthy();
  });

  it("renders the refresh button as an icon-only antd text button", async () => {
    const { container } = await renderLoaded();
    const button = screen.getByRole("button", { name: REFRESH_LABEL });
    expect(button.getAttribute("type")).toBe("button");
    expect(button.className).toContain("ant-btn-text");
    expect(button.className).toContain("ant-btn-icon-only");
    // lucide-react renders for real inside the button (not stubbed).
    expect(button.querySelector("svg.lucide-refresh-cw")).toBeTruthy();
    expect(container.querySelectorAll("button")).toHaveLength(1);
  });
});

describe("HubProviderUsage - 30s polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  async function flush() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  it("schedules exactly one 30000ms interval on mount", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    request.mockResolvedValue(usageOf());
    render(<HubProviderUsage />);
    await flush();
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    expect(setIntervalSpy.mock.calls[0][1]).toBe(30000);
  });

  it("re-polls when the interval elapses", async () => {
    request.mockResolvedValue(usageOf());
    render(<HubProviderUsage />);
    await flush();
    expect(request).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(request).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29999);
    });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("does not re-schedule the interval when a poll re-renders the widget", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    request
      .mockResolvedValueOnce(usageOf({ charged: 100 }))
      .mockResolvedValue(usageOf({ charged: 900 }));
    render(<HubProviderUsage />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    // The loader is wrapped in useCallback([]), so the [load] effect never
    // re-fires even though the render output changed.
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText("900")).toBeTruthy();
  });

  it("clears the interval on unmount and never polls again afterwards", async () => {
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    request.mockResolvedValue(usageOf());
    const { unmount } = render(<HubProviderUsage />);
    await flush();
    expect(request).toHaveBeenCalledTimes(1);
    unmount();
    expect(clearIntervalSpy).toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90000);
    });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("a failed poll surfaces the alert but keeps polling", async () => {
    request
      .mockResolvedValueOnce(usageOf())
      .mockRejectedValueOnce(new Error("hub_budget_exceeded"))
      .mockResolvedValue(usageOf());
    render(<HubProviderUsage />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(screen.getByRole("alert").textContent).toBe(
      "hub.governance.errors.budgetExceeded",
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(request).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("HubProviderUsage - amount row", () => {
  it("renders charged over the token limit", async () => {
    const { container } = await renderLoaded(
      usageOf({ charged: 300, token_limit: 1000 }),
    );
    const amount = container.querySelector(`.${styles.amount}`);
    expect(amount).toBeTruthy();
    expect(amount?.querySelector("strong")?.textContent).toBe("300");
    expect(amount?.querySelector("span")?.textContent).toBe("/ 1,000");
  });

  it("substitutes the unlimited label for a null token limit", async () => {
    const { container } = await renderLoaded(
      usageOf({ token_limit: null, charged: 42 }),
    );
    const amount = container.querySelector(`.${styles.amount}`);
    expect(amount?.querySelector("strong")?.textContent).toBe("42");
    expect(amount?.textContent).toContain("hub.governance.budget.unlimited");
    // A null limit also removes the bar entirely.
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("formats numbers through the active i18n locale", async () => {
    i18nState.language = "de";
    const { container } = await renderLoaded(
      usageOf({ charged: 1000, token_limit: 20000, remaining: 5000 }),
    );
    const amount = container.querySelector(`.${styles.amount}`);
    expect(amount?.querySelector("strong")?.textContent).toBe("1.000");
    expect(amount?.textContent).toContain("/ 20.000");
    expect(screen.getByText("5.000")).toBeTruthy();
  });

  it("formats numbers with the default en locale as thousands separators", async () => {
    const { container } = await renderLoaded(
      usageOf({ charged: 1000, token_limit: 20000 }),
    );
    const amount = container.querySelector(`.${styles.amount}`);
    expect(amount?.querySelector("strong")?.textContent).toBe("1,000");
    expect(amount?.textContent).toContain("/ 20,000");
  });
});

describe("HubProviderUsage - percentage computation", () => {
  it("computes (charged + reserved) / token_limit", async () => {
    await renderLoaded(
      usageOf({ charged: 300, reserved: 200, token_limit: 1000 }),
    );
    expect(progressBar().getAttribute("aria-valuenow")).toBe("50");
    expect(barInner().style.width).toBe("50%");
  });

  it("caps the bar at 100 when usage exceeds the limit", async () => {
    await renderLoaded(
      usageOf({ charged: 80, reserved: 80, token_limit: 100 }),
    );
    expect(progressBar().getAttribute("aria-valuenow")).toBe("100");
    expect(barInner().style.width).toBe("100%");
  });

  it("reports a full bar for an explicit zero limit", async () => {
    await renderLoaded(usageOf({ charged: 5, reserved: 5, token_limit: 0 }));
    expect(progressBar().getAttribute("aria-valuenow")).toBe("100");
  });

  it("always renders the bar with showInfo off, small size and the budget label", async () => {
    await renderLoaded();
    const bar = progressBar();
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.className).toContain("ant-progress-small");
    expect(bar.className).toContain("ant-progress-line");
    // showInfo={false}: antd renders no textual percentage next to the bar.
    expect(bar.textContent).toBe("");
  });

  it("paints the accent colour while the budget is available", async () => {
    await renderLoaded(usageOf({ remaining: 500 }, false));
    expect(progressStatus()).toBe("normal");
    expect(
      barInner().style.getPropertyValue("--progress-line-stroke-color"),
    ).toBe(ACCENT);
  });

  it("paints the error colour once the budget is blocked", async () => {
    await renderLoaded(usageOf({ remaining: 0 }, false));
    expect(progressStatus()).toBe("exception");
    expect(
      barInner().style.getPropertyValue("--progress-line-stroke-color"),
    ).toBe(DANGER);
  });
});

describe("HubProviderUsage - blocked predicate", () => {
  it("is not blocked while remaining is positive and the org is open", async () => {
    const { container } = await renderLoaded(usageOf({ remaining: 1 }, false));
    expect(container.querySelector(`.${styles.warning}`)).toBeNull();
  });

  it("blocks on an exhausted member budget (remaining === 0)", async () => {
    const { container } = await renderLoaded(usageOf({ remaining: 0 }, false));
    const warning = container.querySelector(`.${styles.warning}`);
    expect(warning?.textContent).toBe(
      "hub.governance.member.budgetUnavailable",
    );
  });

  it("blocks on the organization flag even with remaining budget", async () => {
    const { container } = await renderLoaded(usageOf({ remaining: 900 }, true));
    const warning = container.querySelector(`.${styles.warning}`);
    expect(warning?.textContent).toBe(
      "hub.governance.member.budgetUnavailable",
    );
    expect(progressStatus()).toBe("exception");
  });

  it("does not treat a null remaining as exhausted", async () => {
    const { container } = await renderLoaded(
      usageOf({ remaining: null }, false),
    );
    expect(container.querySelector(`.${styles.warning}`)).toBeNull();
    // remaining === null also hides the remaining row.
    expect(screen.queryByText("hub.governance.dashboard.remaining")).toBeNull();
  });

  it("renders only one warning line when both triggers fire", async () => {
    const { container } = await renderLoaded(usageOf({ remaining: 0 }, true));
    expect(container.querySelectorAll(`.${styles.warning}`)).toHaveLength(1);
  });
});

describe("HubProviderUsage - conditional rows", () => {
  it("renders remaining and reserved rows when both apply", async () => {
    await renderLoaded(usageOf({ remaining: 500, reserved: 200 }));
    expect(screen.getByText("hub.governance.dashboard.remaining")).toBeTruthy();
    expect(screen.getByText("500")).toBeTruthy();
    expect(screen.getByText("hub.governance.dashboard.reserved")).toBeTruthy();
    expect(screen.getByText("200")).toBeTruthy();
  });

  it("hides the reserved row when nothing is reserved", async () => {
    await renderLoaded(usageOf({ reserved: 0 }));
    expect(screen.queryByText("hub.governance.dashboard.reserved")).toBeNull();
    expect(screen.getByText("hub.governance.dashboard.remaining")).toBeTruthy();
  });

  it("shows the reserved row for any positive reservation", async () => {
    await renderLoaded(usageOf({ reserved: 1 }));
    expect(screen.getByText("hub.governance.dashboard.reserved")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
  });

  it("shows the remaining row for an explicit zero remaining", async () => {
    await renderLoaded(usageOf({ remaining: 0 }));
    expect(screen.getByText("hub.governance.dashboard.remaining")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
  });

  it("groups each metric into its own CSS-module row", async () => {
    const { container } = await renderLoaded(
      usageOf({ remaining: 500, reserved: 200 }),
    );
    // header row + remaining row + reserved row
    expect(container.querySelectorAll(`.${styles.row}`)).toHaveLength(3);
    expect(container.querySelector(`.${styles.usage}`)).toBeTruthy();
  });
});

describe("HubProviderUsage - error surface", () => {
  async function renderFailed(failure: unknown) {
    request.mockRejectedValue(failure);
    render(<HubProviderUsage />);
    return screen.findByRole("alert");
  }

  it("maps a known transport failure onto its i18n key", async () => {
    const alert = await renderFailed(new Error("Failed to fetch"));
    expect(alert.textContent).toBe("hub.governance.errors.requestFailed");
  });

  it("maps a known hub error code onto its i18n key", async () => {
    const alert = await renderFailed(new Error("hub_budget_exceeded"));
    expect(alert.textContent).toBe("hub.governance.errors.budgetExceeded");
  });

  it("passes an unmapped detail through verbatim", async () => {
    const alert = await renderFailed(new Error("some unusual backend text"));
    expect(alert.textContent).toBe("some unusual backend text");
  });

  it("carries the alert role and the warning class", async () => {
    const alert = await renderFailed(new Error("Failed to fetch"));
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.className).toContain(styles.warning);
  });

  it("suppresses the loading line while an error is showing", async () => {
    await renderFailed(new Error("Failed to fetch"));
    expect(
      screen.queryByText("hub.governance.member.loadingBudget"),
    ).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("still renders the header and the refresh button while failed", async () => {
    await renderFailed(new Error("Failed to fetch"));
    expect(
      screen.getByText("hub.governance.dashboard.monthlyTokens"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: REFRESH_LABEL })).toBeTruthy();
  });

  it("treats a non-Error rejection as an empty message, which keeps the loading line", async () => {
    // The product does setError((e as Error).message). For a thrown string
    // that property is undefined, so the error state stays falsy: no alert is
    // rendered and the loading line is not suppressed. This is asserted
    // through a plain render because renderFailed waits for an alert that,
    // by this contract, can never appear.
    request.mockRejectedValue("plain string failure");
    render(<HubProviderUsage />);
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getByText("hub.governance.member.loadingBudget"),
    ).toBeTruthy();
  });
});

describe("HubProviderUsage - hub-managed data shape", () => {
  it("renders the loading line when the member payload is absent", async () => {
    await renderLoaded(usageOf(null));
    expect(
      screen.getByText("hub.governance.member.loadingBudget"),
    ).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("renders no warning when the member payload is absent and the org is open", async () => {
    const { container } = await renderLoaded(usageOf(null, false));
    expect(container.querySelector(`.${styles.warning}`)).toBeNull();
  });

  it("blocks on the organization flag even without a member payload", async () => {
    const { container } = await renderLoaded(usageOf(null, true));
    expect(container.querySelector(`.${styles.warning}`)?.textContent).toBe(
      "hub.governance.member.budgetUnavailable",
    );
  });
});
