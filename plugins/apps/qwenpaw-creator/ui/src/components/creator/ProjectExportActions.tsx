import { useEffect, useMemo, useState } from "react";
import { Dropdown, message } from "antd";
import { ChevronDown, Download, FileOutput } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProjectDocument } from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { selectTimelineFilmVersionId } from "@/selectors/blueprintSelectors";
import { selectLiveTimelineIds } from "@/selectors/timelineElementSelectors";
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

  // Multi-episode projects expose each selected film by its timeline title.
  // Never infer that an individual episode represents the entire project.
  const films = useMemo(
    () =>
      selectLiveTimelineIds(project).map((timelineId, index) => ({
        timelineId,
        versionId: selectTimelineFilmVersionId(project, timelineId),
        name:
          project.timelines.items[timelineId].title ||
          t("blueprint.episodeN", { n: index + 1 }),
      })),
    [project, t],
  );
  const hasFilm = films.some((film) => film.versionId);

  const downloadFilm = async (film: (typeof films)[number]) => {
    if (!film.versionId) return;
    const url = getArtifactVersionMediaUrl(film.versionId);
    const filename = `${
      film.name || project.name || t("blueprint.finalCut")
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
      phase: "packaging",
    });
    try {
      await saveExportFile(projectId, (receivedBytes, totalBytes) =>
        setExportProgress({
          receivedBytes,
          totalBytes,
          status: "running",
          phase: "downloading",
        }),
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
            ...(films.length > 1
              ? [
                  {
                    type: "group" as const,
                    key: "films",
                    label: t("blueprint.downloadFinal"),
                    children: films.map((film) => ({
                      key: film.timelineId,
                      label: film.name,
                      icon: <Download className="h-3.5 w-3.5" />,
                      disabled: !film.versionId,
                      onClick: () => void downloadFilm(film),
                    })),
                  },
                ]
              : [
                  {
                    key: "download",
                    label: t("blueprint.downloadFinal"),
                    icon: <Download className="h-3.5 w-3.5" />,
                    disabled: !hasFilm,
                    onClick: () => films[0] && void downloadFilm(films[0]),
                  },
                ]),
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
            hasFilm
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
