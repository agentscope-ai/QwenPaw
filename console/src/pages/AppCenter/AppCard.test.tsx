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
  it("renders the plugin.json emoji icon when no image icon is available", () => {
    render(<AppCard app={makeApp()} onClick={vi.fn()} />);

    expect(screen.getByText("🎮")).toBeInTheDocument();
    expect(screen.getByText("Demo App")).toBeInTheDocument();
  });

  it("prefers the image icon over the emoji glyph", () => {
    render(
      <AppCard
        app={makeApp({ icon_url: "/icons/demo.png" })}
        onClick={vi.fn()}
      />,
    );

    expect(screen.queryByText("🎮")).not.toBeInTheDocument();
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

  it("opens the app from the card action", () => {
    const onClick = vi.fn();
    const onUninstall = vi.fn();
    render(
      <AppCard app={makeApp()} onClick={onClick} onUninstall={onUninstall} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "appCenter.openApp" }));

    expect(onClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: "demo-app" }),
    );
    expect(onUninstall).not.toHaveBeenCalled();
  });

  it("triggers uninstall from the card action without opening the app", () => {
    const onClick = vi.fn();
    const onUninstall = vi.fn();
    render(
      <AppCard app={makeApp()} onClick={onClick} onUninstall={onUninstall} />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "appCenter.uninstall" }),
    );

    expect(onUninstall).toHaveBeenCalledWith(
      expect.objectContaining({ id: "demo-app" }),
    );
    expect(onClick).not.toHaveBeenCalled();
  });

  it("hides uninstall when it is not available but keeps open available", () => {
    render(<AppCard app={makeApp()} onClick={vi.fn()} />);

    expect(
      screen.queryByRole("button", { name: "appCenter.uninstall" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "appCenter.openApp" }),
    ).toBeInTheDocument();
  });
});
