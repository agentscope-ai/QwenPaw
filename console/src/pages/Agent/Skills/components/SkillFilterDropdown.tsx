import { useTranslation } from "react-i18next";

export const CATEGORY_PREFIX = "category:";
export const TAG_PREFIX = "tag:";

interface SkillFilterDropdownProps {
  allCategories: string[];
  allTags: string[];
  searchTags: string[];
  setSearchTags: React.Dispatch<React.SetStateAction<string[]>>;
  styles: Record<string, string>;
}

export function SkillFilterDropdown({
  allCategories,
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
      {allCategories.length > 0 && (
        <div className={styles.filterGroup}>
          <div className={styles.filterGroupTitle}>
            {t("skillPool.categories")}
          </div>
          <div className={styles.filterOptions}>
            {allCategories.map((cat) => {
              const value = `${CATEGORY_PREFIX}${cat}`;
              const active = searchTags.includes(value);
              return (
                <div
                  key={cat}
                  className={`${styles.filterOption} ${
                    active ? styles.filterOptionActive : ""
                  }`}
                  onClick={() => toggle(value)}
                >
                  {cat}
                </div>
              );
            })}
          </div>
        </div>
      )}
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
