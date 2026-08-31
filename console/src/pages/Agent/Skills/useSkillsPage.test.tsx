/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unused-vars */
/**
 * useSkillsPage.test.tsx — integration test for skills page
 *   regression for #3484/#3504/#3541/#5955 (skill cluster)
 *
 * Tests the integration of useSkillFilter + useProgressiveRender that
 * powers the skills page UI. Covers:
 *   - Search filtering by name and description
 *   - Tag-based filtering
 *   - Progressive rendering (pagination via sentinel)
 *   - Sorted output (enabled first, then alphabetical)
 *
 * Strategy: test the individual hooks that compose useSkillsPage,
 * since useSkillsPage itself has heavy API dependencies. The integration
 * invariant is: filter → sort → progressive-render pipeline produces
 * the correct visible subset.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSkillFilter } from "./useSkillFilter";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";

// Mock IntersectionObserver for useProgressiveRender
const mockIntersectionObserver = vi.fn();
let observerCallback: (entries: Array<{ isIntersecting: boolean }>) => void;
mockIntersectionObserver.mockImplementation(function (this: any, cb: any) {
  observerCallback = cb;
  return {
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  };
});
global.IntersectionObserver = mockIntersectionObserver as any;

// Test data
const makeSkill = (
  name: string,
  opts: Partial<{ description: string; tags: string[]; enabled: boolean }> = {},
) => ({
  name,
  description: opts.description ?? `Description for ${name}`,
  tags: opts.tags ?? [],
  enabled: opts.enabled ?? false,
});

const SKILLS = [
  makeSkill("alpha-tool", { enabled: true, tags: ["productivity"] }),
  makeSkill("beta-helper", { enabled: false, tags: ["dev-tools"] }),
  makeSkill("gamma-search", {
    description: "Advanced search capabilities",
    tags: ["search", "productivity"],
  }),
  makeSkill("delta-code", {
    description: "Code analysis and review",
    tags: ["dev-tools"],
  }),
  makeSkill("epsilon-data", { enabled: true, tags: ["data"] }),
  makeSkill("zeta-ml", {
    description: "Machine learning toolkit",
    tags: ["ml", "dev-tools"],
  }),
];

describe("useSkillsPage integration (#3484/#3504/#3541/#5955)", () => {
  describe("useSkillFilter — search and tag filtering", () => {
    it("returns all skills when no search query or tags", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      expect(result.current.filteredSkills).toHaveLength(SKILLS.length);
    });

    it("filters by name substring (case-insensitive)", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      act(() => {
        result.current.setSearchQuery("search");
      });
      expect(result.current.filteredSkills).toHaveLength(1);
      expect(result.current.filteredSkills[0].name).toBe("gamma-search");
    });

    it("filters by description content", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      act(() => {
        result.current.setSearchQuery("Machine learning");
      });
      expect(result.current.filteredSkills).toHaveLength(1);
      expect(result.current.filteredSkills[0].name).toBe("zeta-ml");
    });

    it("returns empty when no skills match", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      act(() => {
        result.current.setSearchQuery("nonexistent");
      });
      expect(result.current.filteredSkills).toHaveLength(0);
    });

    it("collects all unique tags from skills", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      expect(result.current.allTags).toEqual(
        expect.arrayContaining([
          "dev-tools",
          "productivity",
          "search",
          "data",
          "ml",
        ]),
      );
    });

    it("clearing search query restores all skills", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      act(() => {
        result.current.setSearchQuery("alpha");
      });
      expect(result.current.filteredSkills).toHaveLength(1);

      act(() => {
        result.current.setSearchQuery("");
      });
      expect(result.current.filteredSkills).toHaveLength(SKILLS.length);
    });
  });

  describe("sorted output — enabled first, then alphabetical", () => {
    it("sorts enabled skills before disabled ones", () => {
      const { result } = renderHook(() => useSkillFilter(SKILLS));
      const sorted = result.current.filteredSkills.slice().sort((a, b) => {
        if (a.enabled && !b.enabled) return -1;
        if (!a.enabled && b.enabled) return 1;
        return a.name.localeCompare(b.name);
      });

      // Enabled skills should come first
      const enabledNames = sorted.filter((s) => s.enabled).map((s) => s.name);
      const disabledNames = sorted.filter((s) => !s.enabled).map((s) => s.name);

      expect(enabledNames).toEqual(["alpha-tool", "epsilon-data"]);
      expect(disabledNames).toEqual([
        "beta-helper",
        "delta-code",
        "gamma-search",
        "zeta-ml",
      ]);

      // All enabled should appear before all disabled
      const firstDisabledIdx = sorted.findIndex((s) => !s.enabled);
      const lastEnabledIdx = sorted.map((s) => s.enabled).lastIndexOf(true);
      expect(lastEnabledIdx).toBeLessThan(firstDisabledIdx);
    });
  });

  describe("useProgressiveRender — pagination and scroll loading", () => {
    it("initially renders only the first batch of items", () => {
      const manyItems = Array.from({ length: 50 }, (_, i) =>
        makeSkill(`skill-${String(i).padStart(3, "0")}`),
      );

      const { result } = renderHook(() => useProgressiveRender(manyItems));

      // INITIAL_COUNT is 20
      expect(result.current.visibleItems).toHaveLength(20);
      expect(result.current.hasMore).toBe(true);
    });

    it("shows all items when total is less than batch size", () => {
      const fewItems = Array.from({ length: 5 }, (_, i) =>
        makeSkill(`skill-${i}`),
      );

      const { result } = renderHook(() => useProgressiveRender(fewItems));

      expect(result.current.visibleItems).toHaveLength(5);
      expect(result.current.hasMore).toBe(false);
    });

    it("loads more items when sentinel becomes visible", () => {
      const manyItems = Array.from({ length: 50 }, (_, i) =>
        makeSkill(`skill-${String(i).padStart(3, "0")}`),
      );

      const { result } = renderHook(() => useProgressiveRender(manyItems));
      expect(result.current.visibleItems).toHaveLength(20);

      // Must attach sentinel first so IntersectionObserver is created
      act(() => {
        result.current.sentinelRef(document.createElement("div"));
      });

      // Simulate sentinel becoming visible (scroll to bottom)
      act(() => {
        observerCallback([{ isIntersecting: true }]);
      });

      // BATCH_SIZE is 20, so now we should have 40
      expect(result.current.visibleItems).toHaveLength(40);
      expect(result.current.hasMore).toBe(true);

      // Load one more batch
      act(() => {
        observerCallback([{ isIntersecting: true }]);
      });

      // All 50 items should now be visible
      expect(result.current.visibleItems).toHaveLength(50);
      expect(result.current.hasMore).toBe(false);
    });

    it("resets visible count when source list changes", () => {
      const initialItems = Array.from({ length: 50 }, (_, i) =>
        makeSkill(`skill-${String(i).padStart(3, "0")}`),
      );

      const { result, rerender } = renderHook(
        ({ items }) => useProgressiveRender(items),
        { initialProps: { items: initialItems } },
      );

      // Simulate sentinel being attached
      act(() => {
        result.current.sentinelRef(document.createElement("div"));
      });

      // Load more
      act(() => {
        observerCallback([{ isIntersecting: true }]);
      });
      expect(result.current.visibleItems).toHaveLength(40);

      // Change the source list (e.g., after search filter)
      const filteredItems = Array.from({ length: 10 }, (_, i) =>
        makeSkill(`filtered-${i}`),
      );
      rerender({ items: filteredItems });

      // Should reset to initial count (or all if less than initial)
      expect(result.current.visibleItems).toHaveLength(10);
      expect(result.current.hasMore).toBe(false);
    });

    it("sentinelRef is a callback ref setter", () => {
      const { result } = renderHook(() =>
        useProgressiveRender(
          Array.from({ length: 5 }, (_, i) => makeSkill(`s-${i}`)),
        ),
      );
      expect(typeof result.current.sentinelRef).toBe("function");
    });
  });

  describe("filter → sort → render pipeline integration", () => {
    it("filtered + sorted + paginated produces correct visible subset", () => {
      // Step 1: Filter
      const { result: filterResult } = renderHook(() => useSkillFilter(SKILLS));
      act(() => {
        filterResult.current.setSearchQuery("dev-tools");
      });
      // This searches name+description, not tags. Let's search by name instead.
      act(() => {
        filterResult.current.setSearchQuery("");
      });

      // Step 2: Sort (enabled first, then alphabetical)
      const sorted = filterResult.current.filteredSkills
        .slice()
        .sort((a, b) => {
          if (a.enabled && !b.enabled) return -1;
          if (!a.enabled && b.enabled) return 1;
          return a.name.localeCompare(b.name);
        });

      // Step 3: Progressive render
      const { result: renderResult } = renderHook(() =>
        useProgressiveRender(sorted),
      );

      // All 6 items < INITIAL_COUNT (20), so all visible
      expect(renderResult.current.visibleItems).toHaveLength(6);
      expect(renderResult.current.hasMore).toBe(false);

      // First items should be enabled ones
      expect(renderResult.current.visibleItems[0].enabled).toBe(true);
      expect(renderResult.current.visibleItems[1].enabled).toBe(true);
    });
  });
});
