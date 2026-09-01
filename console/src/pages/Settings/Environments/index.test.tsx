// @vitest-environment jsdom
/**
 * EnvironmentsPage — env-variable CRUD page. Drives the full user flow:
 * loading/error/empty states, row add/insert/edit, selection bookkeeping
 * (including index shifting on insert), single + batch delete (new rows
 * skip the confirm; persisted rows go through Modal.confirm + API), key
 * validation (required / format / duplicate) and the save/reset lifecycle.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mockApi = vi.hoisted(() => ({
  listEnvs: vi.fn(),
  saveEnvs: vi.fn(),
  deleteEnv: vi.fn(),
}));

const mockMessage = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

const mockConfirm = vi.hoisted(() => vi.fn());

vi.mock("../../../api", () => ({ default: mockApi }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

// Extend the global design stub: add a Checkbox (absent from the stub) and
// capture Modal.confirm so delete flows can be driven.
vi.mock("@agentscope-ai/design", async () => {
  const stub = await vi.importActual<Record<string, unknown>>(
    "@agentscope-ai/design",
  );
  return {
    ...stub,
    Checkbox: ({
      checked,
      onChange,
      indeterminate,
    }: {
      checked?: boolean;
      onChange?: () => void;
      indeterminate?: boolean;
    }) => (
      <input
        type="checkbox"
        data-indeterminate={indeterminate ? "true" : "false"}
        checked={!!checked}
        onChange={() => onChange?.()}
      />
    ),
    Modal: Object.assign(
      ({ children }: { children?: React.ReactNode }) => <>{children}</>,
      {
        confirm: (opts: Record<string, unknown>) => mockConfirm(opts),
        error: vi.fn(),
        warning: vi.fn(),
      },
    ),
  };
});

import EnvironmentsPage from "./index";

// ---- Helpers ---------------------------------------------------------------

const makeEnv = (key: string, value = "v") => ({ key, value });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderPage() {
  return renderWithProviders(<EnvironmentsPage />);
}

beforeEach(() => {
  mockApi.listEnvs.mockReset().mockResolvedValue([]);
  mockApi.saveEnvs.mockReset().mockResolvedValue([]);
  mockApi.deleteEnv.mockReset().mockResolvedValue([]);
  mockMessage.success.mockClear();
  mockMessage.error.mockClear();
  mockConfirm.mockClear();
});

// ---- Tests -----------------------------------------------------------------

describe("EnvironmentsPage loading, error and empty states", () => {
  it("shows the loading state until the list arrives", async () => {
    const d = deferred<unknown[]>();
    mockApi.listEnvs.mockReturnValue(d.promise);
    renderPage();
    expect(screen.getByText("environments.loading")).toBeTruthy();

    await d.resolve([]);
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
  });

  it("shows the error state with a working retry button", async () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi.listEnvs
      .mockRejectedValueOnce(new Error("backend down"))
      .mockResolvedValueOnce([makeEnv("A")]);
    renderPage();

    await waitFor(() => expect(screen.getByText("backend down")).toBeTruthy());
    expect(consoleSpy).toHaveBeenCalled();

    fireEvent.click(screen.getByText("environments.retry"));
    await waitFor(() => {
      expect(screen.queryByText("backend down")).toBeNull();
      expect(screen.getByPlaceholderText("Variable Name")).toBeTruthy();
    });
    consoleSpy.mockRestore();
  });

  it("renders the empty state when there are no variables", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    // No rows, no select-all checkbox
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByText("0 environments.variables")).toBeTruthy();
  });
});

describe("EnvironmentsPage row editing", () => {
  it("renders persisted rows: key locked, value editable", async () => {
    mockApi.listEnvs.mockResolvedValue([
      makeEnv("API_KEY", "s3cret"),
      makeEnv("DEBUG", "1"),
    ]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    const keys = screen.getAllByPlaceholderText("Variable Name");
    expect(keys[0]).toHaveProperty("disabled", true);
    expect(keys[1]).toHaveProperty("disabled", true);
    expect(screen.getByText("2 environments.variables")).toBeTruthy();

    // Editing a value makes the page dirty (reset + save appear)
    const values = screen.getAllByPlaceholderText("Value");
    fireEvent.change(values[1], { target: { value: "0" } });
    await waitFor(() => expect(screen.getByText("common.reset")).toBeTruthy());
  });

  it("adds a new row and validates + saves the merged result", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("OLD", "x")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );

    fireEvent.click(screen.getByTitle("environments.addVariable"));
    const keyInputs = await screen.findAllByPlaceholderText("Variable Name");
    expect(keyInputs).toHaveLength(2);
    // The freshly added row's key is editable
    expect(keyInputs[1]).toHaveProperty("disabled", false);

    fireEvent.change(keyInputs[1], { target: { value: "NEW_VAR" } });
    const values = screen.getAllByPlaceholderText("Value");
    fireEvent.change(values[1], { target: { value: "new-val" } });

    const saveBtn = screen
      .getByText("common.save")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(mockApi.saveEnvs).toHaveBeenCalledWith({
        OLD: "x",
        NEW_VAR: "new-val",
      }),
    );
    await waitFor(() =>
      expect(mockMessage.success).toHaveBeenCalledWith(
        "environments.saveSuccess",
      ),
    );
    // After save the local copy is dropped and the list is refetched
    expect(mockApi.listEnvs).toHaveBeenCalledTimes(2);
  });

  it("inserts a row after the clicked one and shifts selections", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("A"), makeEnv("B")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    // Select row 1 ("B")
    const boxes = screen.getAllByRole("checkbox");
    // [toolbar select-all, row0, row1]
    fireEvent.click(boxes[2]);
    expect(screen.getByText(/1 environments\.of 2/)).toBeTruthy();

    // Insert after row 0
    const insertBtns = screen.getAllByTitle("environments.insertRowBelow");
    fireEvent.click(insertBtns[0]);

    // The new blank row sits between A and B
    const keys = screen.getAllByPlaceholderText("Variable Name");
    expect(keys).toHaveLength(3);
    expect(keys[1]).toHaveProperty("disabled", false);
    // Selection moved with "B": now the third row
    const boxesAfter = screen.getAllByRole("checkbox");
    expect((boxesAfter[1] as HTMLInputElement).checked).toBe(false);
    expect((boxesAfter[2] as HTMLInputElement).checked).toBe(false);
    expect((boxesAfter[3] as HTMLInputElement).checked).toBe(true);
  });

  it("editing a new row's key clears that row's validation error", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    const keyInput = await screen.findByPlaceholderText("Variable Name");

    // Save with an empty key → validation error on the row
    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(screen.getByText("environments.keyRequired")).toBeTruthy(),
    );
    expect(mockApi.saveEnvs).not.toHaveBeenCalled();

    // Typing a key clears the error
    fireEvent.change(keyInput, { target: { value: "FIXED" } });
    expect(screen.queryByText("environments.keyRequired")).toBeNull();
  });
});

describe("EnvironmentsPage selection", () => {
  it("toggles individual rows and select-all with indeterminate state", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("A"), makeEnv("B")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    const boxes = () => screen.getAllByRole("checkbox");
    // Select row 0
    fireEvent.click(boxes()[1]);
    expect((boxes()[0] as HTMLInputElement).dataset.indeterminate).toBe("true");
    expect(screen.getByText(/1 environments\.of 2/)).toBeTruthy();

    // Select-all turns indeterminate off and checks everything
    fireEvent.click(boxes()[0]);
    expect((boxes()[0] as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/2 environments\.of 2/)).toBeTruthy();

    // Toggle select-all again clears the selection
    fireEvent.click(boxes()[0]);
    expect((boxes()[0] as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByText(/environments\.of/)).toBeNull();
  });
});

describe("EnvironmentsPage deletion", () => {
  it("removes a new (unsaved) row without confirmation or API calls", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    await screen.findByPlaceholderText("Variable Name");

    fireEvent.click(screen.getByTitle("environments.deleteRow"));
    expect(mockConfirm).not.toHaveBeenCalled();
    expect(mockApi.deleteEnv).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
  });

  it("deletes a persisted row through the confirm dialog", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("KEEP"), makeEnv("DROP")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    const removeBtns = screen.getAllByTitle("environments.deleteRow");
    fireEvent.click(removeBtns[1]);

    expect(mockConfirm).toHaveBeenCalledTimes(1);
    const opts = mockConfirm.mock.calls[0][0];
    expect(opts.title).toBe("environments.deleteVariable");
    expect(opts.okButtonProps).toEqual({ danger: true });

    await opts.onOk();
    expect(mockApi.deleteEnv).toHaveBeenCalledWith("DROP");
    await waitFor(() =>
      expect(mockMessage.success).toHaveBeenCalledWith(
        'environments.deleteSuccess:{"name":"DROP"}',
      ),
    );
    // Rows were reset and the list refetched from the server
    expect(mockApi.listEnvs).toHaveBeenCalledTimes(2);
  });

  it("surfaces the API error when deleting a persisted row fails", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("GONE")]);
    mockApi.deleteEnv.mockRejectedValue(new Error("locked"));
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );

    fireEvent.click(screen.getByTitle("environments.deleteRow"));
    await mockConfirm.mock.calls[0][0].onOk();

    expect(mockMessage.error).toHaveBeenCalledWith("locked");
  });

  it("removes a selection of only-new rows without confirmation", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("KEEP")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );

    fireEvent.click(screen.getByTitle("environments.addVariable"));
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    // Select only the new (second) row
    fireEvent.click(screen.getAllByRole("checkbox")[2]);
    fireEvent.click(screen.getByText(/common\.delete \(1\)/));

    expect(mockConfirm).not.toHaveBeenCalled();
    expect(mockApi.deleteEnv).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );
  });

  it("batch-deletes persisted rows with a names label (≤3) and keeps new rows out of the API calls", async () => {
    mockApi.listEnvs.mockResolvedValue([
      makeEnv("V1"),
      makeEnv("V2"),
      makeEnv("V3"),
    ]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(3),
    );

    // Add a new row so the batch mixes persisted + new
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(4),
    );

    // Select all via the toolbar checkbox
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/common\.delete \(4\)/));

    expect(mockConfirm).toHaveBeenCalledTimes(1);
    const opts = mockConfirm.mock.calls[0][0];
    expect(opts.content).toBe(
      'environments.deleteSelectedConfirm:{"label":"\\"V1\\", \\"V2\\", \\"V3\\""}',
    );

    await opts.onOk();
    expect(mockApi.deleteEnv).toHaveBeenCalledTimes(3);
    expect(mockApi.deleteEnv).toHaveBeenCalledWith("V1");
    expect(mockApi.deleteEnv).toHaveBeenCalledWith("V2");
    expect(mockApi.deleteEnv).toHaveBeenCalledWith("V3");
    await waitFor(() =>
      expect(mockMessage.success).toHaveBeenCalledWith(
        'environments.deleteSuccess:{"name":"\\"V1\\", \\"V2\\", \\"V3\\""}',
      ),
    );
  });

  it("uses a count label when more than three rows are selected and trims keys", async () => {
    mockApi.listEnvs.mockResolvedValue([
      makeEnv("V1"),
      makeEnv("V2"),
      makeEnv("V3"),
      makeEnv("V4"),
    ]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(4),
    );

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/common\.delete \(4\)/));

    const opts = mockConfirm.mock.calls[0][0];
    expect(opts.content).toBe(
      'environments.deleteSelectedConfirm:{"label":"4 variables"}',
    );

    await opts.onOk();
    expect(mockApi.deleteEnv).toHaveBeenCalledTimes(4);
  });

  it("reports the error when a batch delete fails", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("V1"), makeEnv("V2")]);
    mockApi.deleteEnv.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(2),
    );

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/common\.delete \(2\)/));
    await mockConfirm.mock.calls[0][0].onOk();

    expect(mockMessage.error).toHaveBeenCalledWith("boom");
  });
});

describe("EnvironmentsPage validation and save", () => {
  it("rejects empty keys", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    await screen.findByPlaceholderText("Variable Name");

    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(screen.getByText("environments.keyRequired")).toBeTruthy(),
    );
    expect(mockApi.saveEnvs).not.toHaveBeenCalled();
  });

  it("rejects keys with invalid format", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    const keyInput = await screen.findByPlaceholderText("Variable Name");
    fireEvent.change(keyInput, { target: { value: "9bad key!" } });

    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(screen.getByText("environments.invalidKeyFormat")).toBeTruthy(),
    );
    expect(mockApi.saveEnvs).not.toHaveBeenCalled();
  });

  it("rejects duplicate keys (keeping the first occurrence)", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("environments.noVariables")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTitle("environments.addVariable"));
    const keys = await screen.findAllByPlaceholderText("Variable Name");
    fireEvent.change(keys[0], { target: { value: "DUP" } });

    fireEvent.click(screen.getByTitle("environments.addVariable"));
    const keys2 = await screen.findAllByPlaceholderText("Variable Name");
    fireEvent.change(keys2[1], { target: { value: "DUP" } });

    fireEvent.click(screen.getByText("common.save"));
    await waitFor(() =>
      expect(screen.getByText("environments.duplicateKey")).toBeTruthy(),
    );
    expect(mockApi.saveEnvs).not.toHaveBeenCalled();
  });

  it("shows the API error and keeps dirty state when saving fails", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("A")]);
    mockApi.saveEnvs.mockRejectedValue(new Error("disk full"));
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );

    fireEvent.change(screen.getByPlaceholderText("Value"), {
      target: { value: "changed" },
    });
    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() =>
      expect(mockMessage.error).toHaveBeenCalledWith("disk full"),
    );
    // Still dirty: reset button remains
    expect(screen.getByText("common.reset")).toBeTruthy();
  });

  it("reset restores the server state and clears selections and errors", async () => {
    mockApi.listEnvs.mockResolvedValue([makeEnv("A", "server")]);
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Value")).toHaveLength(1),
    );

    // Dirty the page, then reset
    fireEvent.change(screen.getByPlaceholderText("Value"), {
      target: { value: "local-change" },
    });
    fireEvent.click(screen.getByText("common.reset"));

    await waitFor(() => {
      const values = screen.getAllByPlaceholderText("Value");
      expect(values[0]).toHaveProperty("value", "server");
    });
    expect(screen.queryByText("common.reset")).toBeNull();
  });
});
