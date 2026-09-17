export function ProductSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={className ?? "mb-16"}>
      <header className="mb-6">
        <h3 className="mb-2 text-xl font-bold text-site-text">{title}</h3>
        <p className="max-w-3xl text-sm leading-relaxed text-site-text-muted">
          {description}
        </p>
      </header>
      {children}
    </section>
  );
}

export function PlatformGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2">{children}</div>
  );
}
