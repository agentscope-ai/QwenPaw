import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSkillFilter } from "./useSkillFilter";
import { SKILL_TAG_FILTER_PREFIX } from "@/constants/skill";

interface TestSkill {
  name: string;
  description?: string;
  tags?: string[];
}

const mockSkills: TestSkill[] = [
  {
    name: "CodeGen",
    description: "Generates code from prompts",
    tags: ["ai", "code"],
  },
  {
    name: "Translator",
    description: "Translates between languages",
    tags: ["ai", "language"],
  },
  {
    name: "Formatter",
    description: "Formats source files",
    tags: ["code", "tools"],
  },
  {
    name: "Linter",
    description: "Checks code quality",
    tags: ["code", "quality"],
  },
];

function tagFilter(tag: string) {
  return `${SKILL_TAG_FILTER_PREFIX}${tag}`;
}

describe("useSkillFilter", () => {
  it("returns all skills when no filter is applied", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));
    expect(result.current.filteredSkills).toEqual(mockSkills);
  });

  it("filters by name case-insensitively", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchQuery("codegen");
    });

    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("CodeGen");
  });

  it("filters by description", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchQuery("translates");
    });

    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("Translator");
  });

  it("filters by tags using exact match", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchTags([tagFilter("language")]);
    });

    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("Translator");
  });

  it("combines search query and tag filter", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchQuery("code");
    });
    act(() => {
      result.current.setSearchTags([tagFilter("ai")]);
    });

    // "code" matches CodeGen (name) and Linter (description), tag "ai" narrows to CodeGen only
    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("CodeGen");
  });

  it("collects unique sorted tags from all skills", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));
    expect(result.current.allTags).toEqual([
      "ai",
      "code",
      "language",
      "quality",
      "tools",
    ]);
  });

  it("re-filters skills when searchQuery is updated", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchQuery("formatter");
    });
    expect(result.current.filteredSkills).toHaveLength(1);

    act(() => {
      result.current.setSearchQuery("linter");
    });
    expect(result.current.filteredSkills).toHaveLength(1);
    expect(result.current.filteredSkills[0].name).toBe("Linter");
  });

  it("returns all skills when query is cleared back to empty", () => {
    const { result } = renderHook(() => useSkillFilter(mockSkills));

    act(() => {
      result.current.setSearchQuery("codegen");
    });
    expect(result.current.filteredSkills).toHaveLength(1);

    act(() => {
      result.current.setSearchQuery("");
    });
    expect(result.current.filteredSkills).toEqual(mockSkills);
  });
});
