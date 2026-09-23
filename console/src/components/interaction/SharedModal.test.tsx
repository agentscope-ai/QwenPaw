import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { SharedModal } from "./SharedModal";

function Example() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Configure</button>
      <SharedModal
        title="Model"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
      >
        <input aria-label="Model name" />
      </SharedModal>
    </>
  );
}

describe("SharedModal", () => {
  it("retains modal semantics and can reopen after its exit", async () => {
    render(<Example />);
    const trigger = screen.getByRole("button", { name: "Configure" });
    fireEvent.click(trigger);
    expect(
      await screen.findByRole("dialog", { name: "Model" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Model name" })).toBeVisible(),
    );
  });
});
