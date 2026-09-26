import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RuntimeWorkbench } from "./RuntimeWorkbench";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@agentscope-ai/design", async () => ({
  Tabs: (await import("antd")).Tabs,
}));
const items = [
  {
    key: "reactAgent",
    children: <input aria-label="workspace draft" defaultValue="original" />,
  },
  {
    key: "llmRetry",
    children: <input aria-label="retry draft" defaultValue="3" />,
  },
];
function Harness({
  save = async () => true,
  initial = null,
}: {
  save?: () => Promise<boolean>;
  initial?: string | null;
}) {
  const [key, setKey] = useState(initial);
  return (
    <RuntimeWorkbench
      items={items}
      initialKey={key}
      onSectionChange={setKey}
      onNavigate={save}
    />
  );
}
describe("runtime navigation", () => {
  it("preserves drafts when switching sections", async () => {
    render(<Harness />);
    expect(screen.getByLabelText("workspace draft")).toBeVisible();
    fireEvent.change(screen.getByLabelText("workspace draft"), {
      target: { value: "draft" },
    });
    fireEvent.click(
      screen.getByRole("tab", { name: "runtimeDesign.recovery" }),
    );
    await screen.findByLabelText("retry draft");
    await waitFor(() =>
      expect(screen.getByLabelText("workspace draft")).not.toBeVisible(),
    );
    fireEvent.click(
      screen.getByRole("tab", { name: "runtimeDesign.workspace" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("workspace draft")).toBeVisible(),
    );
    expect(
      (screen.getByLabelText("workspace draft") as HTMLInputElement).value,
    ).toBe("draft");
  });
  it("does not leave an editor when saving fails", async () => {
    const save = vi.fn().mockResolvedValue(false);
    render(<Harness initial="reactAgent" save={save} />);
    fireEvent.click(
      screen.getByRole("tab", { name: "runtimeDesign.recovery" }),
    );
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(screen.getByLabelText("workspace draft")).toBeVisible();
    expect(
      screen.getByRole("tab", { name: "runtimeDesign.workspace" }),
    ).toHaveAttribute("aria-selected", "true");
  });
  it("opens a settings-search deep link directly", () => {
    render(<Harness initial="llmRetry" />);
    expect(screen.getByLabelText("retry draft")).toBeTruthy();
    expect(screen.queryByLabelText("workspace draft")).toBeNull();
  });
});
