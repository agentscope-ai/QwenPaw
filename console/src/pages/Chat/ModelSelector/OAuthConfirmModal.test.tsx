// Unit tests for the provider OAuth confirmation modal.
//
// The modal drives a three step flow: a confirmation screen, a hand-off to an
// external browser window, and a polling loop that ends in success, failure or
// a five minute timeout. Two guards matter most and both are exercised here:
// a start that resolves after the modal was dismissed must not open a browser
// window, and a poll answer that arrives after dismissal must not navigate the
// user away from a modal that is no longer live.
//
// The shared design stub renders Modal children unconditionally, so this file
// overrides it with one that honours `open`; without that, every assertion
// about the closed state would describe the stub rather than the product.
//
// All timers are fake so the 2s polling cadence and the 300s timeout are
// deterministic instead of wall-clock dependent.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { OAuthConfirmModal } from "./OAuthConfirmModal";

const mocks = vi.hoisted(() => ({
  startOAuth: vi.fn(),
  getOAuthStatus: vi.fn(),
  openExternalLink: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("../../../api/modules/provider", () => ({
  providerApi: {
    startOAuth: (...args: unknown[]) => mocks.startOAuth(...args),
    getOAuthStatus: (...args: unknown[]) => mocks.getOAuthStatus(...args),
  },
}));

vi.mock("../../../utils/openExternalLink", () => ({
  openExternalLink: (...args: unknown[]) => mocks.openExternalLink(...args),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: mocks.success, error: mocks.error },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) =>
      params ? `${key}:${JSON.stringify(params)}` : key,
  }),
}));

vi.mock("lucide-react", () => ({
  Loader2: () => <span data-testid="oauth-spinner" />,
  ExternalLink: () => <span data-testid="oauth-external" />,
}));

// Modal only renders while open, and forwards the dismissibility flags so the
// "cannot be dismissed while waiting" contract can be asserted.
vi.mock("@agentscope-ai/design", () => ({
  Modal: ({
    open,
    closable,
    maskClosable,
    children,
  }: {
    open?: boolean;
    closable?: boolean;
    maskClosable?: boolean;
    children?: React.ReactNode;
  }) =>
    open ? (
      <div
        data-testid="oauth-modal"
        data-closable={String(closable)}
        data-mask-closable={String(maskClosable)}
      >
        {children}
      </div>
    ) : null,
  Button: ({
    children,
    onClick,
    ...rest
  }: {
    children?: React.ReactNode;
    onClick?: () => void;
  }) => (
    <button type="button" onClick={onClick} {...rest}>
      {children}
    </button>
  ),
}));

const PROVIDER_ID = "openai";
const PROVIDER_NAME = "OpenAI";
const AUTHORIZE_URL = "https://auth.example.com/authorize?prompt=consent";
const STATE = "state-abc-123";

const TITLE = `modelSelector.oauthTitle:${JSON.stringify({
  provider: PROVIDER_NAME,
})}`;
const DESCRIPTION = `modelSelector.oauthDescription:${JSON.stringify({
  provider: PROVIDER_NAME,
})}`;
const CONNECTED = `modelSelector.oauthConnected:${JSON.stringify({
  provider: PROVIDER_NAME,
})}`;
const CONTINUE_LABEL = "modelSelector.oauthContinue";
const CANCEL_LABEL = "common.cancel";
const WAITING_TITLE = "modelSelector.oauthWaiting";
const WAITING_DESCRIPTION = "modelSelector.oauthWaitingDescription";
const FAILED_COPY = "modelSelector.oauthFailed";
const TIMEOUT_COPY = "modelSelector.oauthTimeout";

function modalElement(
  open: boolean,
  onSuccess: () => void,
  onCancel: () => void,
) {
  return (
    <OAuthConfirmModal
      open={open}
      providerId={PROVIDER_ID}
      providerName={PROVIDER_NAME}
      onSuccess={onSuccess}
      onCancel={onCancel}
    />
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type StartResult = {
  authorize_url: string;
  state: string;
  flow_type: string;
};

const START_OK: StartResult = {
  authorize_url: AUTHORIZE_URL,
  state: STATE,
  flow_type: "oauth",
};

/** Click the confirm-phase continue action and let the start promise settle. */
async function clickContinue() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: CONTINUE_LABEL }));
    await Promise.resolve();
  });
}

/** Advance the fake clock inside act so pending polling work can settle. */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

let onSuccess: ReturnType<typeof vi.fn<() => void>>;
let onCancel: ReturnType<typeof vi.fn<() => void>>;

function renderModal(open = true) {
  return renderWithProviders(modalElement(open, onSuccess, onCancel));
}

beforeEach(() => {
  vi.useFakeTimers();
  onSuccess = vi.fn<() => void>();
  onCancel = vi.fn<() => void>();
  mocks.startOAuth.mockResolvedValue(START_OK);
  mocks.getOAuthStatus.mockResolvedValue({ status: "pending" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("OAuthConfirmModal confirm phase", () => {
  it("introduces the provider and offers continue plus cancel", () => {
    renderModal();

    expect(screen.getByTestId("oauth-modal")).toBeTruthy();
    expect(screen.getByText(TITLE)).toBeTruthy();
    expect(screen.getByText(DESCRIPTION)).toBeTruthy();
    expect(screen.getByRole("button", { name: CONTINUE_LABEL })).toBeTruthy();
    expect(screen.getByRole("button", { name: CANCEL_LABEL })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    expect(mocks.startOAuth).not.toHaveBeenCalled();
    expect(mocks.openExternalLink).not.toHaveBeenCalled();
  });

  it("stays dismissible while the user has not started the flow", () => {
    renderModal();

    const modal = screen.getByTestId("oauth-modal");
    expect(modal.getAttribute("data-closable")).toBe("true");
    expect(modal.getAttribute("data-mask-closable")).toBe("true");
  });

  it("hands the cancel action straight to the parent", () => {
    renderModal();

    fireEvent.click(screen.getByRole("button", { name: CANCEL_LABEL }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.startOAuth).not.toHaveBeenCalled();
  });

  it("renders nothing and starts no polling while mounted closed", async () => {
    renderModal(false);

    expect(screen.queryByTestId("oauth-modal")).toBeNull();

    await tick(300000);

    expect(mocks.startOAuth).not.toHaveBeenCalled();
    expect(mocks.getOAuthStatus).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("returns to the confirm copy when a closed modal is opened again", async () => {
    const view = renderModal();
    await clickContinue();
    expect(screen.getByRole("status")).toBeTruthy();

    view.rerender(modalElement(false, onSuccess, onCancel));
    expect(screen.queryByTestId("oauth-modal")).toBeNull();

    view.rerender(modalElement(true, onSuccess, onCancel));
    expect(screen.getByText(TITLE)).toBeTruthy();
    expect(screen.getByRole("button", { name: CONTINUE_LABEL })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("OAuthConfirmModal starting the flow", () => {
  it("opens the authorize url in a popup and switches to waiting", async () => {
    renderModal();

    await clickContinue();

    expect(mocks.startOAuth).toHaveBeenCalledWith(PROVIDER_ID);
    expect(mocks.openExternalLink).toHaveBeenCalledWith(
      AUTHORIZE_URL,
      "_blank",
      "popup,width=600,height=700",
    );
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText(WAITING_TITLE)).toBeTruthy();
    expect(screen.getByText(WAITING_DESCRIPTION)).toBeTruthy();
    expect(screen.queryByRole("button", { name: CONTINUE_LABEL })).toBeNull();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("stops being dismissible while waiting for the browser hand-off", async () => {
    renderModal();

    await clickContinue();

    const modal = screen.getByTestId("oauth-modal");
    expect(modal.getAttribute("data-closable")).toBe("false");
    expect(modal.getAttribute("data-mask-closable")).toBe("false");
    expect(screen.getByRole("button", { name: CANCEL_LABEL })).toBeTruthy();
  });

  it("ignores a repeated continue click while the first start is in flight", async () => {
    const start = deferred<StartResult>();
    mocks.startOAuth.mockReturnValue(start.promise);
    renderModal();

    const continueButton = screen.getByRole("button", { name: CONTINUE_LABEL });
    await act(async () => {
      fireEvent.click(continueButton);
      fireEvent.click(continueButton);
      await Promise.resolve();
    });

    expect(mocks.startOAuth).toHaveBeenCalledTimes(1);

    await act(async () => {
      start.resolve(START_OK);
    });
    expect(mocks.openExternalLink).toHaveBeenCalledTimes(1);
  });

  it("does not open a browser window when the modal closes before the start resolves", async () => {
    const start = deferred<StartResult>();
    mocks.startOAuth.mockReturnValue(start.promise);
    const view = renderModal();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: CONTINUE_LABEL }));
      await Promise.resolve();
    });
    expect(mocks.startOAuth).toHaveBeenCalledTimes(1);

    view.rerender(modalElement(false, onSuccess, onCancel));
    await act(async () => {
      start.resolve(START_OK);
    });

    expect(mocks.openExternalLink).not.toHaveBeenCalled();
    expect(screen.queryByTestId("oauth-modal")).toBeNull();

    // No polling loop may have been armed by the abandoned start.
    await tick(6000);
    expect(mocks.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("surfaces the backend message when the start rejects with an error", async () => {
    mocks.startOAuth.mockRejectedValue(new Error("provider refused"));
    renderModal();

    await clickContinue();

    expect(mocks.error).toHaveBeenCalledWith("provider refused");
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.openExternalLink).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("falls back to the generic failure copy when the start rejects a non-error", async () => {
    mocks.startOAuth.mockRejectedValue("plain string failure");
    renderModal();

    await clickContinue();

    expect(mocks.error).toHaveBeenCalledWith(FAILED_COPY);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("stays silent when the start fails after the modal was closed", async () => {
    const start = deferred<StartResult>();
    mocks.startOAuth.mockReturnValue(start.promise);
    const view = renderModal();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: CONTINUE_LABEL }));
      await Promise.resolve();
    });
    expect(mocks.startOAuth).toHaveBeenCalledTimes(1);

    view.rerender(modalElement(false, onSuccess, onCancel));
    await act(async () => {
      start.reject(new Error("provider refused"));
    });

    expect(mocks.error).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.openExternalLink).not.toHaveBeenCalled();
  });
});

describe("OAuthConfirmModal polling the authorization status", () => {
  it("polls once per interval with the provider id and the start state", async () => {
    renderModal();
    await clickContinue();

    await tick(2000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(1);
    expect(mocks.getOAuthStatus).toHaveBeenCalledWith(PROVIDER_ID, STATE);

    await tick(2000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("reports success and stops polling once the backend completes", async () => {
    mocks.getOAuthStatus.mockResolvedValue({ status: "completed" });
    renderModal();
    await clickContinue();

    await tick(2000);

    expect(mocks.success).toHaveBeenCalledWith(CONNECTED);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(1);

    await tick(6000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(1);
  });

  it("reports failure and stops polling once the backend fails", async () => {
    mocks.getOAuthStatus.mockResolvedValue({ status: "failed" });
    renderModal();
    await clickContinue();

    await tick(2000);

    expect(mocks.error).toHaveBeenCalledWith(FAILED_COPY);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();

    await tick(6000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(1);
  });

  it("keeps waiting and keeps polling while the backend reports pending", async () => {
    renderModal();
    await clickContinue();

    await tick(6000);

    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(3);
    expect(mocks.success).not.toHaveBeenCalled();
    expect(mocks.error).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("swallows a polling rejection and keeps waiting", async () => {
    mocks.getOAuthStatus.mockRejectedValue(new Error("network down"));
    renderModal();
    await clickContinue();

    await tick(2000);

    expect(mocks.error).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeTruthy();

    await tick(2000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(2);
  });

  it("drops a completed answer that arrives after the modal was closed", async () => {
    const answer = deferred<{ status: string }>();
    mocks.getOAuthStatus.mockReturnValue(answer.promise);
    const view = renderModal();
    await clickContinue();

    // The poll is already awaiting the backend when the modal is dismissed, so
    // the answer lands against a modal that is no longer live.
    await tick(2000);
    view.rerender(modalElement(false, onSuccess, onCancel));
    await act(async () => {
      answer.resolve({ status: "completed" });
    });

    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.success).not.toHaveBeenCalled();
    expect(screen.queryByTestId("oauth-modal")).toBeNull();
  });

  it("drops a failed answer that arrives after the modal was closed", async () => {
    const answer = deferred<{ status: string }>();
    mocks.getOAuthStatus.mockReturnValue(answer.promise);
    const view = renderModal();
    await clickContinue();

    await tick(2000);
    view.rerender(modalElement(false, onSuccess, onCancel));
    await act(async () => {
      answer.resolve({ status: "failed" });
    });

    expect(onCancel).not.toHaveBeenCalled();
    expect(mocks.error).not.toHaveBeenCalled();
  });
});

describe("OAuthConfirmModal timeout", () => {
  it("explains the timeout and cancels after five minutes of waiting", async () => {
    renderModal();
    await clickContinue();

    await tick(300000);

    expect(mocks.error).toHaveBeenCalledWith(TIMEOUT_COPY);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();

    const callsBefore = mocks.getOAuthStatus.mock.calls.length;
    await tick(10000);
    expect(mocks.getOAuthStatus).toHaveBeenCalledTimes(callsBefore);
  });

  it("never reaches the timeout when the authorization completes first", async () => {
    mocks.getOAuthStatus.mockResolvedValue({ status: "completed" });
    renderModal();
    await clickContinue();

    await tick(2000);
    await tick(300000);

    expect(mocks.success).toHaveBeenCalledTimes(1);
    expect(mocks.error).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});

describe("OAuthConfirmModal teardown", () => {
  it("stops polling when the modal unmounts while waiting", async () => {
    const view = renderModal();
    await clickContinue();

    view.unmount();
    await tick(6000);

    expect(mocks.getOAuthStatus).not.toHaveBeenCalled();
  });

  it("stops both the polling and the timeout when the modal is closed", async () => {
    const view = renderModal();
    await clickContinue();

    view.rerender(modalElement(false, onSuccess, onCancel));
    await tick(300000);

    expect(mocks.getOAuthStatus).not.toHaveBeenCalled();
    expect(mocks.error).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
  });
});
