import type { ArtifactVersionDocument } from "@/contracts/creator";

/**
 * Keeps the same DOM and styling as the origin/main Workbench VersionChips.
 * Clicking a chip only switches the locally viewed version; switching the
 * current version is committed explicitly via the adjacent "设为当前"
 * (set as current) button.
 */
export default function ArtifactVersionChips({
  versions,
  currentId,
  viewingId,
  onView,
}: {
  versions: ArtifactVersionDocument[];
  currentId?: string | null;
  viewingId: string | null;
  onView: (id: string) => void;
}) {
  if (versions.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {versions.map((version, index) => {
        const active = version.version_id === viewingId;
        const current = version.version_id === currentId;
        return (
          <button
            key={version.version_id}
            type="button"
            data-artifact-version={version.version_id}
            onClick={() => onView(version.version_id)}
            title={current ? "当前版本" : "历史版本"}
            className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
              active
                ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                current
                  ? "bg-[var(--color-success)]"
                  : "bg-[var(--color-text-tertiary)]"
              }`}
            />
            v{index + 1}
            {current && <span className="opacity-70">·当前</span>}
          </button>
        );
      })}
    </div>
  );
}
