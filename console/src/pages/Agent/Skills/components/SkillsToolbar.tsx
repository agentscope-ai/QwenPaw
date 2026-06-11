import type { Dispatch, SetStateAction } from "react";
import { Input } from "@/components/ui/input";
import { List, LayoutGrid } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SkillFilterDropdown } from "./SkillFilterDropdown";
import styles from "../index.module.less";

interface SkillsToolbarProps {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  searchTags: string[];
  onTagsChange: Dispatch<SetStateAction<string[]>>;
  allTags: string[];
  filterOpen: boolean;
  onFilterOpenChange: (open: boolean) => void;
  viewMode: "card" | "list";
  onViewModeChange: (mode: "card" | "list") => void;
}

export function SkillsToolbar({
  searchQuery,
  onSearchChange,
  searchTags,
  onTagsChange,
  allTags,
  filterOpen,
  onFilterOpenChange,
  viewMode,
  onViewModeChange,
}: SkillsToolbarProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.toolbar}>
      <div className={styles.searchContainer}>
        <Input
          className={styles.searchInput}
          placeholder={t("skills.searchPlaceholder")}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        <div className="relative">
          <div
            className={`${styles.tagSelect} flex flex-wrap items-center gap-1 px-3 py-1.5 border rounded-md cursor-pointer min-h-9 min-w-[160px]`}
            onClick={() => onFilterOpenChange(!filterOpen)}
          >
            {searchTags.length === 0 ? (
              <span className="text-xs text-muted-foreground">
                {t("skills.filterByTag")}
              </span>
            ) : (
              searchTags.map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary"
                >
                  {tag}
                </span>
              ))
            )}
          </div>
          {filterOpen && (
            <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-md">
              {allTags.length > 0 ? (
                <SkillFilterDropdown
                  allTags={allTags}
                  searchTags={searchTags}
                  setSearchTags={onTagsChange}
                  styles={styles}
                />
              ) : (
                <div className={styles.tagSelectEmpty}>
                  {t("skills.noTags")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <div className={styles.toolbarRight}>
        <div className={styles.viewToggle}>
          <button
            className={`${styles.viewToggleBtn} ${
              viewMode === "list" ? styles.viewToggleBtnActive : ""
            }`}
            onClick={() => onViewModeChange("list")}
            title={t("skills.listView")}
          >
            <List size={16} />
          </button>
          <button
            className={`${styles.viewToggleBtn} ${
              viewMode === "card" ? styles.viewToggleBtnActive : ""
            }`}
            onClick={() => onViewModeChange("card")}
            title={t("skills.gridView")}
          >
            <LayoutGrid size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
