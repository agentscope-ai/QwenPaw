import { useEffect, useMemo, useState } from "react";
import { Dropdown, message } from "antd";
import { ChevronDown, Download, FileOutput } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { selectFinalFilmVersionId } from "@/selectors/blueprintSelectors";
import {
  ExportProgressCard,
  saveExportFile,
  type ExportProgressState,
} from "@/components/creator/ProjectImportExport";

/**
 * Project-level export home (design 83:13383 plan header): a 下载/导出
 * dropdown (final cut + project export) plus, on branching projects, the
 * highlighted 导出互动包 button.
 */
export default function ProjectExportActions({
  project,
}: {
  project: ProjectDocument;
}) {
  const { t } = useTranslation();
  const projectId = project.project_id;
  const [exportProgress, setExportProgress] =
    useState<ExportProgressState | null>(null);
  const exporting = exportProgress?.status === "running";

  // The downloadable 成片: only the version the user currently has selected
  // on the single live timeline's render slot, while it is fresh — the
  // selector owns that contract (multi-episode projects have no whole film,
  // and history snapshots never count as timelines).
  const filmVersion = useMemo(() => {
    const wholeFilmId = selectFinalFilmVersionId(project);
    if (!wholeFilmId) return null;
    return {
      versionId: wholeFilmId,
      name: project.assets.artifact_versions_by_id[wholeFilmId]?.name ?? null,
    };
  }, [project]);

  const downloadFilm = async () => {
    if (!filmVersion) return;
    const url = getArtifactVersionMediaUrl(filmVersion.versionId);
    const filename = `${
      filmVersion.name || project.name || t("blueprint.finalCut")
    }.mp4`;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
  };

  const exportProject = async () => {
    if (exporting) return;
    setExportProgress({
      receivedBytes: 0,
      totalBytes: null,
      status: "running",
    });
    try {
      await saveExportFile(projectId, (receivedBytes, totalBytes) =>
        setExportProgress({ receivedBytes, totalBytes, status: "running" }),
      );
      setExportProgress((state) =>
        state ? { ...state, status: "done" } : state,
      );
    } catch (error) {
      setExportProgress(null);
      message.error(
        t("blueprint.exportProjectFailed", {
          detail: (error as Error).message,
        }),
      );
    }
  };

  // The finished card lingers briefly, then clears itself.
  useEffect(() => {
    if (exportProgress?.status !== "done") return;
    const timer = window.setTimeout(() => setExportProgress(null), 5000);
    return () => window.clearTimeout(timer);
  }, [exportProgress]);

  return (
    <>
      <Dropdown
        trigger={["click"]}
        menu={{
          items: [
            {
              key: "download",
              label: t("blueprint.downloadFinal"),
              icon: <Download className="h-3.5 w-3.5" />,
              disabled: !filmVersion,
              onClick: () => void downloadFilm(),
            },
            {
              key: "export",
              label: exporting
                ? t("blueprint.exporting")
                : t("blueprint.exportProject"),
              icon: <FileOutput className="h-3.5 w-3.5" />,
              disabled: exporting,
              onClick: () => void exportProject(),
            },
          ],
        }}
      >
        <button
          type="button"
          data-download-render
          title={
            filmVersion
              ? t("blueprint.downloadFinalTitle")
              : t("blueprint.waitingForFinalCut")
          }
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-xs font-semibold text-[var(--color-text-primary)] transition hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-secondary)]"
        >
          <Download className="h-3.5 w-3.5" />
          {t("blueprint.downloadOrExport")}
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
      </Dropdown>
      {exportProgress && (
        <ExportProgressCard
          projectName={project.name}
          progress={exportProgress}
          onDismiss={() => setExportProgress(null)}
        />
      )}
    </>
  );
}
