import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillSpec } from "../../../api/types";

const harness = vi.hoisted(() => ({
  recoveredSkills: [] as SkillSpec[],
  handleCreate: vi.fn(),
  hardRefresh: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("motion/react", async () => {
  const React = await import("react");
  return {
    LayoutGroup: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
  };
});

vi.mock("@/components/PageHeader", async () => {
  const React = await import("react");
  return {
    PageHeader: ({ extra }: { extra?: React.ReactNode }) =>
      React.createElement("header", null, "skills.title", extra),
  };
});

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  return {
    Button: ({
      children,
      onClick,
    }: {
      children: React.ReactNode;
      onClick?: () => void;
    }) => React.createElement("button", { onClick }, children),
  };
});

vi.mock("antd", async () => {
  const React = await import("react");
  return {
    Alert: ({
      message,
      action,
    }: {
      message: React.ReactNode;
      action?: React.ReactNode;
    }) => React.createElement("div", { role: "alert" }, message, action),
  };
});

vi.mock("./components", async () => {
  const React = await import("react");
  return {
    HeaderActions: ({ onHardRefresh }: { onHardRefresh: () => void }) =>
      React.createElement(
        "div",
        null,
        "header-actions",
        React.createElement(
          "button",
          { type: "button", onClick: onHardRefresh },
          "skills.refreshHint",
        ),
      ),
    SkillsToolbar: () => React.createElement("div", null, "skills-toolbar"),
    SkillCard: ({ skill }: { skill: SkillSpec }) =>
      React.createElement("div", null, `skill:${skill.name}`),
    SkillListItem: ({ skill }: { skill: SkillSpec }) =>
      React.createElement("div", null, `skill:${skill.name}`),
    SkillDrawer: () => null,
    PoolTransferModal: () => null,
    ImportHubModal: () => null,
    ProviderSkillDrawer: () => null,
  };
});

vi.mock("./useSkillsPage", async () => {
  const React = await import("react");
  const noop = () => undefined;
  return {
    useSkillsPage: () => {
      const [state, setState] = React.useState<{
        error: Error | null;
        loading: boolean;
        ready: boolean;
        skills: SkillSpec[];
      }>({
        error: new Error("initial load failed"),
        loading: false,
        ready: false,
        skills: [],
      });
      const refreshSkills = async () => {
        setState((current) => ({ ...current, loading: true }));
        await Promise.resolve();
        setState({
          error: null,
          loading: false,
          ready: true,
          skills: harness.recoveredSkills,
        });
      };
      return {
        ...state,
        channelOptions: {
          options: [],
          loading: false,
          error: false,
          loaded: true,
          onRetry: noop,
        },
        getChannelName: (key: string) => key,
        providerSkills: [],
        visibleSkills: state.skills,
        sortedSkills: state.skills,
        hasMore: false,
        sentinelRef: { current: null },
        poolSkills: [],
        allTags: [],
        conflictRenameModal: null,
        uploading: false,
        importing: false,
        drawerOpen: false,
        drawerLoading: false,
        editingSkillName: "",
        importModalOpen: false,
        setImportModalOpen: noop,
        editingSkill: null,
        form: {},
        fileInputRef: { current: null },
        poolModal: null,
        setPoolModal: noop,
        selectedSkills: new Set<string>(),
        batchModeEnabled: false,
        viewMode: "card" as const,
        setViewMode: noop,
        filterOpen: false,
        setFilterOpen: noop,
        searchQuery: "",
        setSearchQuery: noop,
        searchTags: [],
        setSearchTags: noop,
        handleCreate: harness.handleCreate,
        handleEdit: noop,
        handleToggleEnabled: noop,
        handleDelete: noop,
        handleDrawerClose: noop,
        handleSubmit: noop,
        handleUploadToPool: noop,
        handleDownloadFromPool: noop,
        handleBatchEnable: noop,
        handleBatchDisable: noop,
        handleBatchDelete: noop,
        handleUploadClick: noop,
        handleFileChange: noop,
        handleConfirmImport: noop,
        closeImportModal: noop,
        closePoolModal: noop,
        toggleSelect: noop,
        selectAll: noop,
        clearSelection: noop,
        toggleBatchMode: noop,
        toggleEnabled: noop,
        refreshSkills,
        hardRefresh: harness.hardRefresh,
        cancelImport: noop,
      };
    },
  };
});

import SkillsPage from ".";

describe("SkillsPage load recovery", () => {
  beforeEach(() => {
    harness.recoveredSkills = [];
    harness.handleCreate.mockReset();
    harness.hardRefresh.mockReset();
  });

  it.each([
    { label: "empty", recoveredSkills: [] as SkillSpec[] },
    {
      label: "populated",
      recoveredSkills: [
        {
          name: "saved-skill",
          description: "Persisted",
          source: "local",
          enabled: true,
        },
      ] as SkillSpec[],
    },
  ])(
    "keeps failure distinct until Retry restores a real $label result",
    async ({ recoveredSkills }) => {
      harness.recoveredSkills = recoveredSkills;
      const user = userEvent.setup();
      render(<SkillsPage />);

      expect(screen.getByRole("alert")).toHaveTextContent("skills.loadFailed");
      expect(screen.queryByText("skills.emptyStateTitle")).toBeNull();
      expect(screen.queryByText("skills.emptyStateCreate")).toBeNull();
      expect(screen.queryByText("header-actions")).toBeNull();

      await user.click(
        screen.getByRole("button", {
          name: "common.retry",
        }),
      );

      if (recoveredSkills.length === 0) {
        expect(await screen.findByText("skills.emptyStateTitle")).toBeVisible();
        await user.click(
          screen.getByRole("button", { name: "skills.emptyStateCreate" }),
        );
        expect(harness.handleCreate).toHaveBeenCalledTimes(1);
      } else {
        expect(
          await screen.findByText(`skill:${recoveredSkills[0].name}`),
        ).toBeVisible();
        expect(screen.queryByText("skills.emptyStateTitle")).toBeNull();
      }
      expect(screen.getByText("header-actions")).toBeVisible();
      await user.click(
        screen.getByRole("button", { name: "skills.refreshHint" }),
      );
      expect(harness.hardRefresh).toHaveBeenCalledTimes(1);
    },
  );
});
