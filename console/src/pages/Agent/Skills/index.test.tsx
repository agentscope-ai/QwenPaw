// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  refreshSkills: vi.fn(),
  hardRefresh: vi.fn(),
  marketProps: undefined as
    | { installTarget: string; onInstalled?: () => void }
    | undefined,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("react-router-dom", () => ({
  useSearchParams: () => [new URLSearchParams("view=market"), vi.fn()],
}));
vi.mock("@ant-design/icons", () => ({
  ArrowLeftOutlined: () => null,
  PlusOutlined: () => null,
}));
vi.mock("@agentscope-ai/design", () => ({ Button: () => null }));
vi.mock("@/components/PageHeader", () => ({ PageHeader: () => null }));
vi.mock("./components", () => ({
  SkillCard: () => null,
  SkillDrawer: () => null,
  PoolTransferModal: () => null,
  ImportHubModal: () => null,
  HeaderActions: () => null,
  SkillsToolbar: () => null,
  SkillListItem: () => null,
  getSkillVisual: vi.fn(),
}));
vi.mock("./useSkillsPage", () => ({
  useSkillsPage: () => ({
    visibleSkills: [],
    sortedSkills: [],
    selectedSkills: new Set<string>(),
    refreshSkills: hoisted.refreshSkills,
    hardRefresh: hoisted.hardRefresh,
  }),
}));
vi.mock("../../Settings/Market/MarketPanel", () => ({
  MarketPanel: (props: { installTarget: string; onInstalled?: () => void }) => {
    hoisted.marketProps = props;
    return null;
  },
}));

import SkillsPage from "./index";

describe("SkillsPage market view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.marketProps = undefined;
  });

  it("refreshes workspace skills when a market install completes", () => {
    render(<SkillsPage />);

    expect(hoisted.marketProps?.installTarget).toBe("workspace");
    act(() => hoisted.marketProps?.onInstalled?.());
    expect(hoisted.refreshSkills).toHaveBeenCalledTimes(1);
    expect(hoisted.hardRefresh).not.toHaveBeenCalled();
  });
});
