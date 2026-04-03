import { useTranslation } from "react-i18next";

interface SkillFilterDropdownProps {
  allCategories: string[];
  allTags: string[];
  setSearchTags: React.Dispatch<React.SetStateAction<string[]>>;
  styles: Record<string, string>;
}

export function SkillFilterDropdown({
  allCategories,
  allTags,
  setSearchTags,
  styles,
}: SkillFilterDropdownProps) {
  const { t } = useTranslation();
  return (
    <div>
      {allCategories.length > 0 && (
        <div className={styles.filterGroup}>
          <div className={styles.filterGroupTitle}>📂 {t("skillPool.categories")}</div>
          <div className={styles.filterOptions}>
            {allCategories.map((cat) => (
              <div
                key={cat}
                className={styles.filterOption}
                onClick={() => {
                  const tag = `📂:${cat}`;
                  setSearchTags((prev) =>
                    prev.includes(tag) ? prev : [...prev, tag],
                  );
                }}
              >
                {cat}
              </div>
            ))}
          </div>
        </div>
      )}
      {allTags.length > 0 && (
        <div className={styles.filterGroup}>
          <div className={styles.filterGroupTitle}>🏷️ {t("skillPool.tags")}</div>
          <div className={styles.filterOptions}>
            {allTags.map((tag) => (
              <div
                key={tag}
                className={styles.filterOption}
                onClick={() => {
                  const tagValue = `🏷️:${tag}`;
                  setSearchTags((prev) =>
                    prev.includes(tagValue) ? prev : [...prev, tagValue],
                  );
                }}
              >
                {tag}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
