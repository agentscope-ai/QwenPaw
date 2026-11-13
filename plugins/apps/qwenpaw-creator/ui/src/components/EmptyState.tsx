import { ReactNode } from "react";
import { Button } from "antd";
import { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
  extra?: ReactNode;
}

export default function EmptyState({
  icon: Icon,
  title,
  description,
  actionText,
  onAction,
  extra,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-xl bg-[var(--color-accent-soft)]">
        <Icon className="h-7 w-7 text-[var(--color-accent)]" />
      </div>
      <h3 className="mb-2 text-lg font-semibold text-[var(--color-text-primary)]">
        {title}
      </h3>
      {description && (
        <p className="mb-6 max-w-xs text-center text-sm text-[var(--color-text-secondary)]">
          {description}
        </p>
      )}
      {actionText && onAction && (
        <Button type="primary" onClick={onAction} className="!rounded-lg">
          {actionText}
        </Button>
      )}
      {extra}
    </div>
  );
}
