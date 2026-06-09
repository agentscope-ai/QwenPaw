import { useTranslation } from "react-i18next";
import { SKILL_TAG_FILTER_PREFIX } from "@/constants/skill";

/** @deprecated Import SKILL_TAG_FILTER_PREFIX from "@/constants/skill" instead */
export const TAG_PREFIX = SKILL_TAG_FILTER_PREFIX;

interface SkillFilterDropdownProps {
  allTags: string[];
  searchTags: string[];
  setSearchTags: React.Dispatch<React.SetStateAction<string[]>>;
  styles: Record<string, string>;
}

export function SkillFilterDropdown({
  allTags,
  searchTags,
  setSearchTags,
  styles,
}: SkillFilterDropdownProps) {
  const { t } = useTranslation();

  const toggle = (value: string) => {
    setSearchTags((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  return (
    <div>
      {allTags.length > 0 && (
        <div className={styles.filterGroup}>
          <div className={styles.filterGroupTitle}>{t("skillPool.tags")}</div>
          <div className={styles.filterOptions}>
            {allTags.map((tag) => {
              const value = `${TAG_PREFIX}${tag}`;
              const active = searchTags.includes(value);
              return (
                <div
                  key={tag}
                  className={`${styles.filterOption} ${
                    active ? styles.filterOptionActive : ""
                  }`}
                  onClick={() => toggle(value)}
                >
                  {tag}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
