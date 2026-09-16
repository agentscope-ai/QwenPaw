import { describe, expect, it } from "vitest";
import type { MenuItem } from "../plugins/registry/types";
import { Capability } from "./capabilities";
import { filterMenuByCapabilities } from "./filterMenu";

const menu: MenuItem[] = [
  { id: "core.agents", label: "Agents" },
  {
    id: "core.settings-group",
    label: "Settings",
    isGroup: true,
    __children: [
      {
        id: "core.models",
        label: "Models",
        capability: Capability.PlatformSettingsManage,
      },
      {
        id: "core.users",
        label: "Users",
        capability: Capability.UsersManage,
      },
    ],
  } as MenuItem,
];

function ids(items: MenuItem[]): string[] {
  return items.flatMap((item) => [
    item.id,
    ...ids((item as MenuItem & { __children?: MenuItem[] }).__children ?? []),
  ]);
}

describe("filterMenuByCapabilities", () => {
  it("hides admin entries and empty groups from a member", () => {
    expect(ids(filterMenuByCapabilities(menu, "multi_user", "member"))).toEqual([
      "core.agents",
    ]);
  });

  it("keeps the admin and legacy menus unchanged", () => {
    expect(filterMenuByCapabilities(menu, "multi_user", "admin")).toBe(menu);
    expect(filterMenuByCapabilities(menu, "legacy", null)).toBe(menu);
  });
});
