import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DeleteAction } from "./DeleteAction";

describe("DeleteAction", () => {
  it("requires confirmation and Escape never invokes deletion", async () => {
    const onConfirm = vi.fn();
    render(<DeleteAction label="Delete backup" onConfirm={onConfirm} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Delete backup" }),
    );
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: "Delete backup" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Delete backup" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
  it("keeps a failed operation available for retry", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("offline"));
    render(<DeleteAction label="Delete backup" onConfirm={onConfirm} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Delete backup" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Retry"),
    );
    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
  });
});
