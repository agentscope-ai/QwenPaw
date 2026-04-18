import defaultStyles from "../index.module.less";

interface SkillCategoryTagsProps {
  categories?: string[];
  tags?: string[];
  styles?: Record<string, string>;
}

export function SkillCategoryBadges({
  categories,
  styles = defaultStyles,
}: Pick<SkillCategoryTagsProps, "categories" | "styles">) {
  if (!categories?.length) return null;
  return (
    <>
      {categories.map((cat) => (
        <span key={cat} className={styles.categoryChip}>
          {cat}
        </span>
      ))}
    </>
  );
}

export function SkillTagChips({
  tags,
  styles = defaultStyles,
}: Pick<SkillCategoryTagsProps, "tags" | "styles">) {
  if (!tags?.length) return null;
  return (
    <div className={styles.tagChips}>
      {tags.map((tag) => (
        <span key={tag} className={styles.tagChip}>
          {tag}
        </span>
      ))}
    </div>
  );
}

export function SkillCategoriesAndTags({
  categories,
  tags,
  styles = defaultStyles,
}: SkillCategoryTagsProps) {
  if (!categories?.length && !tags?.length) return null;
  return (
    <div className={styles.categoriesTagsContainer}>
      {!!categories?.length && (
        <div className={styles.metaRow}>
          <span className={styles.metaIcon}>📂</span>
          <div className={styles.metaContent}>
            {categories.map((cat) => (
              <span key={cat} className={styles.categoryChip}>
                {cat}
              </span>
            ))}
          </div>
        </div>
      )}
      {!!tags?.length && (
        <div className={styles.metaRow}>
          <span className={styles.metaIcon}>🏷️</span>
          <div className={styles.metaContent}>
            {tags.map((tag) => (
              <span key={tag} className={styles.tagChip}>
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function SkillTags({
  tags,
  styles = defaultStyles,
}: Pick<SkillCategoryTagsProps, "tags" | "styles">) {
  if (!tags?.length) return null;
  return (
    <div className={styles.tagsContainer}>
      <div className={styles.metaRow}>
        <span className={styles.metaIcon}>🏷️</span>
        <div className={styles.metaContent}>
          {tags.map((tag) => (
            <span key={tag} className={styles.tagChip}>
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
