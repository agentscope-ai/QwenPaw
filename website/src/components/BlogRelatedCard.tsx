import type { BlogRelatedMeta } from "@/lib/parseBlogMarkdown";

type BlogRelatedCardProps = {
  related: BlogRelatedMeta;
};

/** Renders plugin/skill meta from blog frontmatter `related`. */
export function BlogRelatedCard({ related }: BlogRelatedCardProps) {
  const hasItems = (related.items?.length ?? 0) > 0;

  return (
    <aside className="blog-related-card mb-6" aria-label={related.heading}>
      <p className="blog-related-card__heading">{related.heading}</p>
      {related.description && (
        <p className="blog-related-card__desc">{related.description}</p>
      )}
      {hasItems && (
        <ul className="blog-related-card__list">
          {related.items!.map((item) => (
            <li key={`${item.label}-${item.name}`}>
              <span className="blog-related-card__item-label">
                {item.label}:{" "}
              </span>
              {item.href ? (
                <a
                  href={item.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="blog-related-card__link"
                >
                  {item.name}
                </a>
              ) : (
                <span className="blog-related-card__item-name">
                  {item.name}
                </span>
              )}
              {item.description && (
                <p className="blog-related-card__desc">{item.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      {related.linkUrl && related.linkText && (
        <p className="blog-related-card__cta">
          <a
            href={related.linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="blog-related-card__link"
          >
            {related.linkText}
          </a>
        </p>
      )}
    </aside>
  );
}
