// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppCard, type AppCardData } from "./AppCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

function makeApp(overrides: Partial<AppCardData> = {}): AppCardData {
  return {
    id: "demo-app",
    name: "Demo App",
    version: "1.2.3",
    description: "A demo app",
    category: "tools",
    icon: "🎮",
    entry_page: "/apps/demo-app",
    launch_scope: "page",
    status: "active",
    ...overrides,
  };
}

describe("AppCard", () => {
  it("never renders the raw icon text (emoji) and falls back to Lucide", () => {
    render(<AppCard app={makeApp()} onClick={vi.fn()} />);

    expect(screen.queryByText("🎮")).not.toBeInTheDocument();
    expect(screen.getByText("Demo App")).toBeInTheDocument();
  });

  it("opens the app when the card body is clicked", () => {
    const onClick = vi.fn();
    render(<AppCard app={makeApp()} onClick={onClick} />);

    fireEvent.click(screen.getByText("Demo App"));

    expect(onClick).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "demo-app",
      }),
    );
  });

  it.each(["Enter", " "])("opens the app with the %s key", (key) => {
    const onClick = vi.fn();
    render(<AppCard app={makeApp()} onClick={onClick} />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Demo App" }), {
      key,
    });

    expect(onClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "demo-app" }),
    );
  });

  it("exposes an always-visible more-actions button that does not open the app", () => {
    const onClick = vi.fn();
    const onUninstall = vi.fn();
    render(
      <AppCard app={makeApp()} onClick={onClick} onUninstall={onUninstall} />,
    );

    const moreBtn = screen.getByRole("button", {
      name: "appCenter.moreActions",
    });
    fireEvent.click(moreBtn);

    expect(onClick).not.toHaveBeenCalled();
  });

  it("triggers uninstall from the more-actions menu without opening the app", async () => {
    const onClick = vi.fn();
    const onUninstall = vi.fn();
    render(
      <AppCard app={makeApp()} onClick={onClick} onUninstall={onUninstall} />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "appCenter.moreActions" }),
    );
    fireEvent.click(await screen.findByText("appCenter.uninstall"));

    expect(onUninstall).toHaveBeenCalledWith(
      expect.objectContaining({ id: "demo-app" }),
    );
    expect(onClick).not.toHaveBeenCalled();
  });

  it("hides the more-actions button when uninstall is not available", () => {
    render(<AppCard app={makeApp()} onClick={vi.fn()} />);

    expect(
      screen.queryByRole("button", { name: "appCenter.moreActions" }),
    ).not.toBeInTheDocument();
  });
});
