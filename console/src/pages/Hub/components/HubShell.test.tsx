import { fireEvent, render, screen } from "@testing-library/react";
import { Grid } from "antd";
import { afterAll, expect, it, vi } from "vitest";
import HubShell from "./HubShell";

vi.hoisted(() => {
  window.__qpBase = "/app/qwenpaw/web";
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../components/LanguageSwitcher", () => ({
  default: () => null,
}));
const originalLocation = Object.getOwnPropertyDescriptor(window, "location")!;
afterAll(() => {
  Object.defineProperty(window, "location", originalLocation);
  delete window.__qpBase;
  vi.restoreAllMocks();
});

it("returns from Hub to the runtime-mounted console root", () => {
  vi.spyOn(Grid, "useBreakpoint").mockReturnValue({ md: true });
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { pathname: "/app/qwenpaw/web/hub", assign },
  });
  render(
    <HubShell
      navigation={[]}
      section="overview"
      onNavigate={vi.fn()}
      healthy
      isDark={false}
      onToggleTheme={vi.fn()}
      onLogout={vi.fn()}
      onRefresh={vi.fn()}
      refreshing={false}
      loading={false}
    >
      Overview
    </HubShell>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "hub.actions.backToQwenPaw" }),
  );
  expect(assign).toHaveBeenCalledWith("/app/qwenpaw/web/");
});
