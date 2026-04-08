import { useMemo, useState } from "react";
import { CATEGORY_PREFIX, TAG_PREFIX } from "./components/SkillFilterDropdown";

interface Filterable {
  name: string;
  description?: string;
  categories?: string[];
  tags?: string[];
}

export function useSkillFilter<T extends Filterable>(skills: T[]) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTags, setSearchTags] = useState<string[]>([]);

  const allCategories = useMemo(
    () => Array.from(new Set(skills.flatMap((s) => s.categories || []))).sort(),
    [skills],
  );
  const allTags = useMemo(
    () => Array.from(new Set(skills.flatMap((s) => s.tags || []))).sort(),
    [skills],
  );

  const selectedCategories = useMemo(
    () =>
      searchTags
        .filter((t) => t.startsWith(CATEGORY_PREFIX))
        .map((t) => t.slice(CATEGORY_PREFIX.length)),
    [searchTags],
  );
  const selectedTags = useMemo(
    () =>
      searchTags
        .filter((t) => t.startsWith(TAG_PREFIX))
        .map((t) => t.slice(TAG_PREFIX.length)),
    [searchTags],
  );

  const filteredSkills = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return skills.filter((skill) => {
      const matchesText =
        !q ||
        skill.name.toLowerCase().includes(q) ||
        (skill.description || "").toLowerCase().includes(q);
      const matchesCategory =
        selectedCategories.length === 0 ||
        selectedCategories.some((cat) => skill.categories?.includes(cat));
      const matchesTag =
        selectedTags.length === 0 ||
        selectedTags.some((tag) => skill.tags?.includes(tag));
      return matchesText && matchesCategory && matchesTag;
    });
  }, [skills, searchQuery, selectedCategories, selectedTags]);

  return {
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allCategories,
    allTags,
    filteredSkills,
  };
}
