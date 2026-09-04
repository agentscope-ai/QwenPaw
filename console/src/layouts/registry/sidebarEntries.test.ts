import { describe, expect, it } from "vitest";

import type { FlatMenuEntry } from "./adapter";
import type { MenuItem } from "../../plugins/registry/types";
import {
  filterSidebarMenuItems,
  orderSidebarEntries,
  partitionSidebarEntries,
} from "./sidebarEntries";

type TreeMenuItem = MenuItem & { __children?: TreeMenuItem[] };

const entry = (key: string): FlatMenuEntry => ({
  key,
  label: key,
  icon: null,
  path: `/${key}`,
});

describe("partitionSidebarEntries", () => {
  it("separates work, global, and plugin shortcuts", () => {
    const result = partitionSidebarEntries(
      [
        entry("core.inbox"),
        entry("core.marketplace"),
        entry("core.files"),
        entry("plugin.work"),
      ],
      [entry("core.security"), entry("plugin.settings")],
    );

    expect(result.work.map((item) => item.key)).toEqual(["core.files"]);
    expect(result.global.map((item) => item.key)).toEqual(["core.security"]);
    expect(result.plugins.map((item) => item.key)).toEqual([
      "plugin.work",
      "plugin.settings",
    ]);
  });

  it("keeps inbox and marketplace visible without preferences", () => {
    const items: TreeMenuItem[] = [
      {
        id: "core.inbox",
        location: "primary.agentScoped",
        label: "Inbox",
      },
      {
        id: "core.marketplace",
        location: "primary.agentScoped",
        label: "Marketplace",
      },
    ];

    expect(
      filterSidebarMenuItems(items, new Set(), new Set()).map(
        (item) => item.id,
      ),
    ).toEqual(["core.inbox", "core.marketplace"]);
  });

  it("deduplicates a plugin while preserving first-seen order", () => {
    const result = partitionSidebarEntries(
      [entry("plugin.shared"), entry("plugin.first")],
      [entry("plugin.shared"), entry("plugin.last")],
    );

    expect(result.plugins.map((item) => item.key)).toEqual([
      "plugin.shared",
      "plugin.first",
      "plugin.last",
    ]);
  });

  it("keeps registry order while recursively selecting nested leaves", () => {
    const items: TreeMenuItem[] = [
      {
        id: "core.group",
        location: "primary.settings",
        label: "Group",
        __children: [
          {
            id: "plugin.before",
            location: "primary.settings",
            label: "Before",
          },
          {
            id: "nested.group",
            location: "primary.settings",
            label: "Nested",
            __children: [
              {
                id: "core.security",
                location: "primary.settings",
                label: "Security",
              },
              {
                id: "plugin.after",
                location: "primary.settings",
                label: "After",
              },
            ],
          },
        ],
      },
    ];

    expect(
      filterSidebarMenuItems(
        items,
        new Set(["core.security"]),
        new Set<string>(),
      ).map((item) => item.id),
    ).toEqual(["plugin.before", "core.security", "plugin.after"]);
  });

  it("does not expose an empty group as a navigation entry", () => {
    const items: TreeMenuItem[] = [
      {
        id: "plugin.empty-group",
        location: "primary.settings",
        label: "Empty group",
        __children: [],
      },
    ];

    expect(filterSidebarMenuItems(items, new Set(), new Set())).toHaveLength(0);
  });
});

describe("orderSidebarEntries", () => {
  it("uses preference order without changing the remaining registry order", () => {
    const result = orderSidebarEntries(
      [
        entry("core.files"),
        entry("plugin.first"),
        entry("core.models"),
        entry("core.environments"),
        entry("plugin.last"),
      ],
      ["core.files", "core.environments", "core.models"],
    );

    expect(result.map((item) => item.key)).toEqual([
      "core.files",
      "core.environments",
      "core.models",
      "plugin.first",
      "plugin.last",
    ]);
  });
});
