import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import HistoryPageSizeInput from "./index";
import {
  getHistoryPageSize,
  resetHistoryPageSizeForTests,
  setHistoryPageSize,
} from "../../sessionApi/historyPageSize";

describe("HistoryPageSizeInput", () => {
  beforeEach(() => {
    resetHistoryPageSizeForTests();
  });

  afterEach(() => {
    resetHistoryPageSizeForTests();
  });

  it("commits a new page size on blur", async () => {
    const user = userEvent.setup();
    const onCommitted = vi.fn();
    renderWithProviders(<HistoryPageSizeInput onCommitted={onCommitted} />);
    const input = screen.getByRole("spinbutton");
    await user.clear(input!);
    await user.type(input!, "200");
    input!.blur();
    await waitFor(() => expect(getHistoryPageSize()).toBe(200));
    expect(onCommitted).toHaveBeenCalledWith(200);
  });

  it("restores the last valid value on empty input and does not commit", async () => {
    const user = userEvent.setup();
    const onCommitted = vi.fn();
    setHistoryPageSize(80);
    renderWithProviders(<HistoryPageSizeInput onCommitted={onCommitted} />);
    const input = screen.getByRole("spinbutton");
    await user.clear(input!);
    input!.blur();
    await waitFor(() => expect(getHistoryPageSize()).toBe(80));
    expect(onCommitted).not.toHaveBeenCalled();
  });
});
