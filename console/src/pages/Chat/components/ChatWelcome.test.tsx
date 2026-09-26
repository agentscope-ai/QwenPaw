import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatWelcome } from "./ChatWelcome";

describe("ChatWelcome", () => {
  it("submits the original query from an accessible prompt button", () => {
    const onSubmit = vi.fn();
    render(
      <ChatWelcome
        greeting="Welcome"
        prompts={[{ label: "Explore skills", value: "List my skills" }]}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explore skills" }));
    expect(onSubmit).toHaveBeenCalledWith({ query: "List my skills" });
    expect(screen.getByRole("heading", { name: "Welcome" })).toBeVisible();
  });
});
