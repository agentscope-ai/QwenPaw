import type { ReactNode } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { SessionThinking } from "./SessionThinking";
import { sessionThinkingApi } from "./sessionThinkingApi";
import type { ThinkingPreference, ThinkingView } from "./types";

vi.mock("./sessionThinkingApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sessionThinkingApi")>()),
  sessionThinkingApi: { get: vi.fn(), set: vi.fn() },
}));
vi.mock("../../pages/Chat/ModelSelector/ModelPickerPopover", () => ({
  ModelPickerPopover: ({
    children,
    content,
  }: {
    children: ReactNode;
    content: ReactNode;
  }) => (
    <>
      {children}
      {content}
    </>
  ),
}));

const view: ThinkingView = {
  model: "fixture-model",
  model_key: "fixture:fixture-model",
  control: {
    kind: "effort",
    efforts: ["low", "medium", "high"],
    supports_off: true,
  },
  value: { level: "low" },
  effective: { level: "low" },
  source: "session",
  reason: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function choose(key: string, keyCode: number) {
  const slider = screen.getByRole("slider");
  fireEvent.keyDown(slider, { key, keyCode });
  fireEvent.keyUp(slider, { key, keyCode });
}

async function ready() {
  await waitFor(() =>
    expect(screen.getByRole("slider")).not.toHaveAttribute(
      "aria-disabled",
      "true",
    ),
  );
}

beforeEach(() => {
  vi.mocked(sessionThinkingApi.get).mockReset();
  vi.mocked(sessionThinkingApi.set).mockReset();
});

it.each(["blur", "Enter"])(
  "saves a budget edited from Off on %s",
  async (commit) => {
    const off: ThinkingView = {
      ...view,
      control: {
        kind: "budget",
        efforts: [],
        supports_off: true,
        budget_min: 1024,
        budget_max: 32768,
      },
      value: { level: "off" },
      effective: { level: "off" },
    };
    vi.mocked(sessionThinkingApi.get).mockResolvedValue(off);
    vi.mocked(sessionThinkingApi.set).mockImplementation(
      async (_agent, _chat, value) => ({ ...off, value }),
    );
    renderWithProviders(
      <SessionThinking agentId={`budget-${commit}`} sessionId="s" chatId="c" />,
    );
    await ready();
    fireEvent.click(
      screen.getByRole("button", { name: "thinkingControl.budget" }),
    );
    const input = screen.getByRole("spinbutton", {
      name: "thinkingControl.budget",
    });
    fireEvent.change(input, { target: { value: "4096" } });
    if (commit === "blur") fireEvent.blur(input);
    else fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledExactlyOnceWith(
        `budget-${commit}`,
        "c",
        { level: "budget", budget_tokens: 4096 },
        view.model_key,
      ),
    );
  },
);

it.each([false, true])(
  "finishes submitted saves after switching away (first fails=%s)",
  async (fails) => {
    const first = deferred<ThinkingView>();
    const second = deferred<ThinkingView>();
    vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
    vi.mocked(sessionThinkingApi.set)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const agent = `switch-${fails}`;
    const { rerender } = renderWithProviders(
      <SessionThinking agentId={agent} sessionId="a" chatId="a" />,
    );
    await ready();
    choose("End", 35);
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1),
    );
    choose("ArrowLeft", 37);
    rerender(<SessionThinking agentId={agent} sessionId="b" chatId="b" />);
    await ready();
    await act(async () => {
      if (fails) first.reject(new Error("fixture save failure"));
      else first.resolve({ ...view, value: { level: "high" } });
    });
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledTimes(2),
    );
    expect(sessionThinkingApi.set).toHaveBeenLastCalledWith(
      agent,
      "a",
      { level: "medium" },
      view.model_key,
    );
    await act(async () =>
      second.resolve({ ...view, value: { level: "medium" } }),
    );
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "1");
  },
);

it.each([false, true])(
  "waits for the same chat's writes after return or remount (remount=%s)",
  async (remount) => {
    let saved: ThinkingPreference = { level: "low" };
    const first = deferred<ThinkingView>();
    const second = deferred<ThinkingView>();
    vi.mocked(sessionThinkingApi.get).mockImplementation(async () => ({
      ...view,
      value: saved,
    }));
    vi.mocked(sessionThinkingApi.set)
      .mockImplementationOnce(async () => {
        const result = await first.promise;
        saved = result.value;
        return result;
      })
      .mockImplementationOnce(async () => {
        const result = await second.promise;
        saved = result.value;
        return result;
      })
      .mockImplementation(async (_agent, _chat, value) => {
        saved = value;
        return { ...view, value };
      });
    const agent = `return-${remount}`;
    const original = renderWithProviders(
      <SessionThinking agentId={agent} sessionId="a" chatId="chat-a" />,
    );
    await ready();
    choose("End", 35);
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1),
    );
    choose("ArrowLeft", 37);
    if (remount) {
      original.unmount();
      renderWithProviders(
        <SessionThinking
          agentId={agent}
          sessionId="new-runtime"
          chatId="chat-a"
        />,
      );
    } else {
      original.rerender(
        <SessionThinking agentId={agent} sessionId="b" chatId="chat-b" />,
      );
      await ready();
      original.rerender(
        <SessionThinking agentId={agent} sessionId="a" chatId="chat-a" />,
      );
    }
    const readsBefore = vi.mocked(sessionThinkingApi.get).mock.calls.length;
    await act(async () => {
      await Promise.resolve();
    });
    expect(sessionThinkingApi.get).toHaveBeenCalledTimes(readsBefore);
    await act(async () => first.resolve({ ...view, value: { level: "high" } }));
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledTimes(2),
    );
    expect(sessionThinkingApi.get).toHaveBeenCalledTimes(readsBefore);
    await act(async () =>
      second.resolve({ ...view, value: { level: "medium" } }),
    );
    await ready();
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "2");
    choose("ArrowLeft", 37);
    await waitFor(() =>
      expect(sessionThinkingApi.set).toHaveBeenCalledTimes(3),
    );
    expect(
      vi.mocked(sessionThinkingApi.set).mock.calls.map((call) => call[2]),
    ).toEqual([{ level: "high" }, { level: "medium" }, { level: "low" }]);
    await ready();
    expect(saved).toEqual({ level: "low" });
  },
);

it("does not block another agent using the same chat ID", async () => {
  const first = deferred<ThinkingView>();
  vi.mocked(sessionThinkingApi.get).mockResolvedValue(view);
  vi.mocked(sessionThinkingApi.set)
    .mockReturnValueOnce(first.promise)
    .mockImplementation(async (_agent, _chat, value) => ({ ...view, value }));
  const { rerender } = renderWithProviders(
    <SessionThinking
      agentId="independent-a"
      sessionId="s"
      chatId="same-chat"
    />,
  );
  await ready();
  choose("End", 35);
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(1));
  rerender(
    <SessionThinking
      agentId="independent-b"
      sessionId="s"
      chatId="same-chat"
    />,
  );
  await ready();
  choose("ArrowRight", 39);
  await waitFor(() => expect(sessionThinkingApi.set).toHaveBeenCalledTimes(2));
  expect(sessionThinkingApi.set).toHaveBeenLastCalledWith(
    "independent-b",
    "same-chat",
    { level: "medium" },
    view.model_key,
  );
  await act(async () => first.resolve({ ...view, value: { level: "high" } }));
  expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "2");
});
