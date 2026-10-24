import { createContext, useContext, type ReactNode } from "react";
import styles from "./index.module.less";

type PageShellMode = "standard" | "compat";

export interface PageShellProps {
  title: ReactNode;
  description?: ReactNode;
  center?: ReactNode;
  extra?: ReactNode;
  subRow?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  mode?: PageShellMode;
}

const PageShellContext = createContext(false);

export function PageShell({
  title,
  description,
  center,
  extra,
  subRow,
  children,
  className,
  contentClassName,
  mode = "standard",
}: PageShellProps) {
  const nested = useContext(PageShellContext);
  const compatibilityMode = mode === "compat";

  return (
    <PageShellContext.Provider value>
      <div
        className={`${compatibilityMode ? styles.compat : styles.shell} ${
          className ?? ""
        }`.trim()}
        data-page-shell={mode}
      >
        {!nested && compatibilityMode && (
          <h1 className={styles.srOnly} data-page-title="sr-only">
            {title}
          </h1>
        )}
        {!compatibilityMode && (
          <header className={styles.header}>
            <div className={styles.leading}>
              {nested ? (
                <div className={styles.title}>{title}</div>
              ) : (
                <h1 className={styles.title} data-page-title="visible">
                  {title}
                </h1>
              )}
              {description && (
                <p className={styles.description}>{description}</p>
              )}
              {subRow && <div className={styles.subRow}>{subRow}</div>}
            </div>
            {center && <div className={styles.center}>{center}</div>}
            {extra && <div className={styles.extra}>{extra}</div>}
          </header>
        )}
        <div
          className={`${
            compatibilityMode ? styles.compatContent : styles.content
          } ${contentClassName ?? ""}`.trim()}
        >
          {children}
        </div>
      </div>
    </PageShellContext.Provider>
  );
}
