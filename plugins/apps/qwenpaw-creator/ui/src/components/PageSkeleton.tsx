import { Skeleton } from "antd";

interface PageSkeletonProps {
  type?: "grid" | "list" | "editor";
}

export default function PageSkeleton({ type = "list" }: PageSkeletonProps) {
  if (type === "grid") {
    return (
      <div className="page-container py-8">
        <div className="flex items-center gap-6 mb-8">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton.Button
              key={i}
              active
              size="small"
              style={{ width: 80 }}
            />
          ))}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="surface overflow-hidden">
              <Skeleton.Image
                active
                style={{ width: "100%", height: 200 }}
                className="!w-full !h-[200px]"
              />
              <div className="p-4">
                <Skeleton
                  active
                  paragraph={{ rows: 1 }}
                  title={{ width: "60%" }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === "list") {
    return (
      <div className="page-container py-8">
        <div className="mb-8">
          <Skeleton.Button active size="large" style={{ width: 200 }} />
        </div>
        <div className="surface p-8">
          <div className="mb-6">
            <Skeleton.Button active size="small" style={{ width: 120 }} />
          </div>
          <div className="space-y-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="py-3 px-2">
                <Skeleton
                  active
                  paragraph={{ rows: 0 }}
                  title={{ width: `${60 + i * 5}%` }}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (type === "editor") {
    return (
      <div className="h-full flex flex-col bg-[var(--color-bg-layout)]">
        <div className="flex h-14 items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4">
          {[1, 2, 3].map((i) => (
            <Skeleton.Button
              key={i}
              active
              size="small"
              style={{ width: 32 }}
            />
          ))}
        </div>
        <div className="flex-1 bg-[var(--color-bg-layout)] p-6">
          <Skeleton active paragraph={{ rows: 12 }} />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--color-bg-primary)] p-8">
      <Skeleton active paragraph={{ rows: 6 }} />
    </div>
  );
}
