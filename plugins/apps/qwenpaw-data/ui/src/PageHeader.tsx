import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className = "",
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`qwenpaw-data-page-header ${className}`.trim()}>
      <div className="qwenpaw-data-page-header__copy">
        <span className="qwenpaw-data-eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p className="qwenpaw-data-page-header__description">{description}</p>
      </div>
      {actions ? (
        <div className="qwenpaw-data-page-header__actions">{actions}</div>
      ) : null}
    </header>
  );
}
