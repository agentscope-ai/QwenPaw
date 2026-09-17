import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EnvRow } from "./EnvRow";

const handlers = {
  onToggle: vi.fn(),
  onChange: vi.fn(),
  onInsert: vi.fn(),
  onRemove: vi.fn(),
};

describe("EnvRow", () => {
  it("does not render a reveal control or persisted value for a configured key", () => {
    render(
      <EnvRow
        row={{ key: "API_KEY", value: "", configured: true }}
        idx={0}
        checked={false}
        {...handlers}
      />,
    );

    const valueInput = screen.getByPlaceholderText("********");
    expect(valueInput).toHaveAttribute("type", "password");
    expect(valueInput).toHaveValue("");
    expect(screen.queryByTitle(/show value|显示值/i)).not.toBeInTheDocument();
  });

  it("marks a persisted key for replacement only after a new value is typed", () => {
    render(
      <EnvRow
        row={{ key: "API_KEY", value: "", configured: true }}
        idx={0}
        checked={false}
        {...handlers}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("********"), {
      target: { value: "replacement" },
    });

    expect(handlers.onChange).toHaveBeenCalledWith(0, "value", "replacement");
  });
});
