import defaultStyles from "../index.module.less";

interface SkillTagsProps {
  tags?: string[];
  styles?: Record<string, string>;
}

export function SkillTagChips({
  tags,
  styles = defaultStyles,
}: SkillTagsProps) {
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

export function SkillTags({ tags, styles = defaultStyles }: SkillTagsProps) {
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
