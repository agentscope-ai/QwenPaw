import type { Dispatch, SetStateAction } from "react";
import { Input, Select } from "@agentscope-ai/design";
import { UnorderedListOutlined, AppstoreOutlined } from "@ant-design/icons";
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
        <Select
          mode="multiple"
          className={styles.tagSelect}
          placeholder={t("skills.filterByTag")}
          value={searchTags}
          onChange={onTagsChange}
          open={filterOpen}
          onDropdownVisibleChange={onFilterOpenChange}
          allowClear
          maxTagCount="responsive"
          notFoundContent={<></>}
          dropdownRender={() =>
            allTags.length > 0 ? (
              <SkillFilterDropdown
                allTags={allTags}
                searchTags={searchTags}
                setSearchTags={onTagsChange}
                styles={styles}
              />
            ) : (
              <div className={styles.tagSelectEmpty}>{t("skills.noTags")}</div>
            )
          }
        />
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
            <UnorderedListOutlined />
          </button>
          <button
            className={`${styles.viewToggleBtn} ${
              viewMode === "card" ? styles.viewToggleBtnActive : ""
            }`}
            onClick={() => onViewModeChange("card")}
            title={t("skills.gridView")}
          >
            <AppstoreOutlined />
          </button>
        </div>
      </div>
    </div>
  );
}
