// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ServiceCard } from "./ServiceCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("ServiceCard", () => {
  it("opens configuration from the card surface without swallowing independent actions", () => {
    const configure = vi.fn();
    const remove = vi.fn();
    render(
      <ServiceCard
        name="Example"
        metadata="Remote"
        enabled
        onConfigure={configure}
        onToggle={vi.fn()}
        actions={<button onClick={remove}>Delete</button>}
      />,
    );
    fireEvent.click(screen.getByText("Remote"));
    expect(configure).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledTimes(1);
    expect(configure).toHaveBeenCalledTimes(1);
  });
  it("keeps configuration separate from toggling and prevents duplicate pending toggles", async () => {
    let finish!: () => void;
    const onToggle = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const onConfigure = vi.fn();
    render(
      <ServiceCard
        name="Example"
        enabled
        onConfigure={onConfigure}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Example" }));
    expect(onConfigure).toHaveBeenCalledTimes(1);
    const toggle = screen.getByRole("switch", {
      name: "common.disable: Example",
    });
    fireEvent.click(toggle);
    expect(toggle).toBeDisabled();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onConfigure).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    expect(toggle).toBeEnabled();
  });
});
