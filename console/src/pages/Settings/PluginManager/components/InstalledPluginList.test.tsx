// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PluginInfo } from "@/api/modules/plugin";
import { InstalledPluginList } from "./InstalledPluginList";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      (
        ({
          "pluginManager.statusLoaded": "Running",
          "pluginManager.statusUnloaded": "Not loaded",
          "pluginManager.statusError": "Error",
        }) as Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: () => false }));

const props = {
  loading: false,
  uninstallingId: null,
  onRefresh: vi.fn(),
  onUninstall: vi.fn(),
  updates: new Map(),
  updatesLoading: false,
  updatingId: null,
  updatingAll: false,
  onUpdate: vi.fn(),
  onUpdateAll: vi.fn(),
};

function plugin(loaded: boolean, status?: string): PluginInfo {
  return {
    id: "demo",
    name: "Demo",
    version: "1.0.0",
    description: "",
    author: "",
    loaded,
    plugin_type: "general",
    enabled: true,
    ...(status === undefined ? {} : { status }),
  };
}

function expectTags(text: string, color: string, count: number) {
  const labels = screen.getAllByText(text);
  expect(labels).toHaveLength(count);
  for (const label of labels) {
    expect(label.closest(".ant-tag")).toHaveClass(`ant-tag-${color}`);
  }
}

describe("installed plugin status", () => {
  it.each([
    [true, "failed", "Error", "error"],
    [false, "failed", "Error", "error"],
    [true, "active", "Running", "success"],
    [true, undefined, "Running", "success"],
    [false, undefined, "Not loaded", "default"],
  ] as const)(
    "renders loaded=%s status=%s consistently in all views",
    (loaded, status, text, color) => {
      render(
        <InstalledPluginList {...props} plugins={[plugin(loaded, status)]} />,
      );
      expectTags(text, color, 1);
      if (status === "failed") {
        expect(screen.queryByText("Running")).not.toBeInTheDocument();
        expect(screen.queryByText("Not loaded")).not.toBeInTheDocument();
      }
      fireEvent.click(screen.getByLabelText("skills.listView"));
      // The desktop table and its responsive row both render real status tags.
      expectTags(text, color, 2);
    },
  );

  it("clears the red error tag when refreshed data reports active", () => {
    const { rerender } = render(
      <InstalledPluginList {...props} plugins={[plugin(true, "failed")]} />,
    );
    expectTags("Error", "error", 1);
    fireEvent.click(screen.getByLabelText("pluginManager.catalogRefresh"));
    expect(props.onRefresh).toHaveBeenCalledOnce();
    rerender(
      <InstalledPluginList {...props} plugins={[plugin(true, "active")]} />,
    );
    expectTags("Running", "success", 1);
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("skills.listView"));
    expectTags("Running", "success", 2);
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
  });
});
