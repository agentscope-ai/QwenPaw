import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RefreshCw } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { IconButton } from "./IconButton";

describe("IconButton", () => {
  it("provides a named Lucide-only action and preserves loading semantics", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <IconButton
        icon={RefreshCw}
        label="Refresh providers"
        onClick={onClick}
      />,
    );

    const button = screen.getByRole("button", { name: "Refresh providers" });
    expect(button).toHaveAttribute("data-icon-button");
    expect(button.querySelector("svg.lucide-refresh-cw")).not.toBeNull();
    await user.hover(button);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Refresh providers",
    );
    await user.click(button);
    expect(onClick).toHaveBeenCalledOnce();

    rerender(
      <IconButton
        icon={RefreshCw}
        label="Refresh providers"
        loading
        onClick={onClick}
      />,
    );
    expect(button).toBeDisabled();
  });
});
