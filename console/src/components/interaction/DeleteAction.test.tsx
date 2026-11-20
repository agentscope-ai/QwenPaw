import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { describe, expect, it, vi } from "vitest";
import { DeleteAction } from "./DeleteAction";

function renderDeleteAction(onConfirm: () => void | Promise<void>) {
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <DeleteAction
        label="Delete this backup?"
        confirmText="Delete backup"
        onConfirm={onConfirm}
      />
    </ConfigProvider>,
  );
  return screen.getByRole("button", { name: "Delete this backup?" });
}

describe("DeleteAction", () => {
  it("requires confirmation and Escape never invokes deletion", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const trigger = renderDeleteAction(onConfirm);
    await user.click(trigger);
    expect(onConfirm).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Delete backup" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("blocks duplicate submission and keeps keyboard focus for retry after failure", async () => {
    const user = userEvent.setup();
    let reject!: (error: Error) => void;
    const onConfirm = vi.fn().mockImplementationOnce(
      () =>
        new Promise<void>((_, fail) => {
          reject = fail;
        }),
    );
    const trigger = renderDeleteAction(onConfirm);
    await user.click(trigger);
    const confirm = screen.getByRole("button", { name: "Delete backup" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.keyboard(" ");
    await user.keyboard("{Enter}{Escape}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await act(async () => reject(new Error("offline")));
    expect(screen.getByRole("alert")).not.toBeEmptyDOMElement();
    expect(confirm).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(2);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});
