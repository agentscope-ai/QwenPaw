import styles from "../index.module.less";

interface SkillMetaProps {
  categories?: string[];
  tags?: string[];
}

export function SkillCategoryBadges({ categories }: Pick<SkillMetaProps, "categories">) {
  if (!categories?.length) return null;
  return (
    <>
      {categories.map((cat) => (
        <span key={cat} className={styles.categoryBadge}>
          {cat}
        </span>
      ))}
    </>
  );
}

export function SkillTagChips({ tags }: Pick<SkillMetaProps, "tags">) {
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
