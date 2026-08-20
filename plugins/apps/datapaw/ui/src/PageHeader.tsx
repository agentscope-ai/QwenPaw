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
    <header className={`datapaw-page-header ${className}`.trim()}>
      <div className="datapaw-page-header__copy">
        <span className="datapaw-eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p className="datapaw-page-header__description">{description}</p>
      </div>
      {actions ? (
        <div className="datapaw-page-header__actions">{actions}</div>
      ) : null}
    </header>
  );
}
