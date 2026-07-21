// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  handleRefresh: vi.fn(),
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
  AppstoreOutlined: () => null,
  ArrowLeftOutlined: () => null,
  CloseOutlined: () => null,
  DeleteOutlined: () => null,
  ReloadOutlined: () => null,
  SendOutlined: () => null,
  SyncOutlined: () => null,
  UnorderedListOutlined: () => null,
}));
vi.mock("@agentscope-ai/design", () => ({
  Button: () => null,
  Input: { Search: () => null },
  Select: () => null,
  Tooltip: () => null,
}));
vi.mock("antd", () => ({ Badge: () => null }));
vi.mock("@/components/PageHeader", () => ({ PageHeader: () => null }));
vi.mock("./components", () => ({
  BroadcastModal: () => null,
  ImportBuiltinModal: () => null,
  PoolSkillCard: () => null,
  PoolSkillListItem: () => null,
  PoolSkillDrawer: () => null,
}));
vi.mock("../../Agent/Skills/components/ImportHubModal", () => ({
  ImportHubModal: () => null,
}));
vi.mock("../../Agent/Skills/components/SkillFilterDropdown", () => ({
  SkillFilterDropdown: () => null,
}));
vi.mock("../../Agent/Skills/components/AddSkillDropdown", () => ({
  AddSkillDropdown: () => null,
}));
vi.mock("./builtinNotice", () => ({ getBuiltinNoticeLines: () => [] }));
vi.mock("../../../hooks/useProgressiveRender", () => ({
  useProgressiveRender: () => ({
    visibleItems: [],
    hasMore: false,
    sentinelRef: { current: null },
  }),
}));
vi.mock("./useSkillPool", () => ({
  useSkillPool: () => ({
    builtinNotice: null,
    sortedSkills: [],
    handleRefresh: hoisted.handleRefresh,
  }),
}));
vi.mock("../Market/MarketPanel", () => ({
  MarketPanel: (props: { installTarget: string; onInstalled?: () => void }) => {
    hoisted.marketProps = props;
    return null;
  },
}));

import SkillPoolPage from "./index";

describe("SkillPoolPage market view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.marketProps = undefined;
  });

  it("refreshes the skill pool when a market install completes", () => {
    render(<SkillPoolPage />);

    expect(hoisted.marketProps?.installTarget).toBe("pool");
    act(() => hoisted.marketProps?.onInstalled?.());
    expect(hoisted.handleRefresh).toHaveBeenCalledTimes(1);
  });
});
