import { describe, expect, it } from "vitest";

import type { FlatMenuEntry } from "./adapter";
import type { MenuItem } from "../../plugins/registry/types";
import {
  filterSidebarMenuItems,
  partitionSidebarEntries,
  splitSidebarEntriesForDisplay,
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
      [entry("core.inbox"), entry("core.files"), entry("plugin.work")],
      [entry("core.security"), entry("plugin.settings")],
    );

    expect(result.work.map((item) => item.key)).toEqual(["core.files"]);
    expect(result.global.map((item) => item.key)).toEqual(["core.security"]);
    expect(result.plugins.map((item) => item.key)).toEqual([
      "plugin.work",
      "plugin.settings",
    ]);
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

  it("shows five custom entries directly and puts the rest in overflow", () => {
    const entries = Array.from({ length: 7 }, (_, index) =>
      entry(`plugin.${index + 1}`),
    );

    const result = splitSidebarEntriesForDisplay(entries);

    expect(result.direct.map((item) => item.key)).toEqual([
      "plugin.1",
      "plugin.2",
      "plugin.3",
      "plugin.4",
      "plugin.5",
    ]);
    expect(result.overflow.map((item) => item.key)).toEqual([
      "plugin.6",
      "plugin.7",
    ]);
  });

  it("does not create overflow when custom entries do not exceed five", () => {
    const entries = Array.from({ length: 5 }, (_, index) =>
      entry(`core.${index + 1}`),
    );

    const result = splitSidebarEntriesForDisplay(entries);

    expect(result.direct).toHaveLength(5);
    expect(result.overflow).toHaveLength(0);
  });
});
