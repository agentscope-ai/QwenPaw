import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RestoreAgentTable from "./RestoreAgentTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));

const rows = [
  {
    key: "a",
    aid: "a",
    name: "Alpha",
    isExisting: true,
    currentWorkspaceDir: "C:\\Users\\work\\Alpha",
  },
  {
    key: "b",
    aid: "b",
    name: "Beta",
    isExisting: false,
    currentWorkspaceDir: "",
  },
];

function Preview({ onChange = vi.fn() }) {
  const [selected, setSelected] = useState(["a", "b"]);
  return (
    <RestoreAgentTable
      allAgentRows={rows}
      selectedAgents={selected}
      onSelectionChange={(ids) => {
        setSelected(ids);
        onChange(ids);
      }}
      detailLoading={false}
      defaultWorkspaceDir="/work/new"
      includeAgents
      onIncludeAgentsChange={vi.fn()}
      summaryText={null}
    />
  );
}

describe("RestoreAgentTable", () => {
  it("preserves selections outside the search when deselecting a visible agent", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Preview onChange={onChange} />);
    await user.type(
      screen.getByPlaceholderText("backup.agentSearchPlaceholder"),
      "Alpha",
    );
    const row = screen.getByText("Alpha").closest("tr")!;
    await user.click(within(row).getByRole("checkbox"));
    expect(onChange).toHaveBeenLastCalledWith(["b"]);
    await user.click(within(row).getByRole("checkbox"));
    expect(new Set(onChange.mock.lastCall![0])).toEqual(new Set(["a", "b"]));
    expect(onChange.mock.lastCall![0]).toHaveLength(2);
  });

  it("shows full destination paths and exposes a keyboard-operable disclosure", async () => {
    const user = userEvent.setup();
    render(<Preview />);
    expect(screen.getByText("C:\\Users\\work\\Alpha")).toBeTruthy();
    expect(screen.getByText("/work/new/b")).toBeTruthy();
    const toggle = screen.getByRole("button", { name: "backup.scopeAgents" });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Alpha")).toBeNull();
  });
});
