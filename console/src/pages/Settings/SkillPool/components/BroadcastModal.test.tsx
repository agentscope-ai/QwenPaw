/**
 * BroadcastModal.test.tsx — cancel must stay reachable during a download.
 *
 * Regression: antd 5.29 short-circuits `onCancel` whenever `confirmLoading`
 * is set (`modal/Modal.js`), so binding the busy state to that prop turned
 * "Cancel import" into a button that looked enabled and did nothing.
 *
 * This drives the real modal footer: start a download whose promise stays
 * pending, then click the cancel button and expect the job canceller to be
 * reached. With the old `confirmLoading` binding the click never arrives.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { BroadcastModal } from "./BroadcastModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@number-flow/react", () => ({ default: () => null }));

// The design package resolves its antd re-exports differently under Vitest.
vi.mock("@agentscope-ai/design", () => ({
  Button: ({
    children,
    onClick,
    disabled,
    ...rest
  }: {
    children?: React.ReactNode;
    onClick?: () => void;
    disabled?: boolean;
  }) => (
    <button type="button" onClick={onClick} disabled={disabled} {...rest}>
      {children}
    </button>
  ),
  Input: () => null,
  Select: () => null,
  Tooltip: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

const SKILLS: PoolSkillSpec[] = [
  { name: "demo-skill", source: "external", tags: [] },
];

const WORKSPACES: WorkspaceSkillSummary[] = [
  { agent_id: "ws-a", agent_name: "Workspace A", skill_names: [] },
];

describe("BroadcastModal cancel handling", () => {
  it("routes the cancel click to the job canceller while a download runs", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const onCancelDownload = vi.fn();
    const onConfirm = vi.fn(() => new Promise<void>(() => {}));

    render(
      <BroadcastModal
        open
        skills={SKILLS}
        workspaces={WORKSPACES}
        initialSkillNames={["demo-skill"]}
        downloadState="running"
        onCancel={onCancel}
        onCancelDownload={onCancelDownload}
        onConfirm={onConfirm}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "skillPool.allWorkspaces" }),
    );
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));

    await user.click(
      screen.getByRole("button", { name: "skills.cancelImport" }),
    );

    expect(onCancelDownload).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
