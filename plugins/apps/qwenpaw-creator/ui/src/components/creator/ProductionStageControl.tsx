import { useState } from "react";
import { Modal, message } from "antd";
import { useTranslation } from "react-i18next";
import { creatorRequest, jsonBody } from "@/api/creator/client";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";

export default function ProductionStageControl({
  projectId,
}: {
  projectId: string;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const etag = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.etag : null,
  );
  const patching = useProjectSnapshotStore(
    (state) => state.projectId === projectId && state.patching,
  );
  if (!project || project.settings.production_stage !== "script") return null;

  const confirmScript = async (etag: string) => {
    setBusy(true);
    try {
      await creatorRequest(
        `/projects/${encodeURIComponent(projectId)}/production-stage`,
        {
          method: "POST",
          body: jsonBody({ stage: "media", projectEtag: etag }),
        },
      );
      await useProjectSnapshotStore.getState().pollOnce(projectId);
    } catch (error) {
      message.error((error as Error).message || t("productionStage.failed"));
      await useProjectSnapshotStore
        .getState()
        .pollOnce(projectId)
        .catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };
  const requestConfirmation = () => {
    if (!etag) return;
    const current = etag;
    Modal.confirm({
      title: t("productionStage.confirmTitle"),
      content: t("productionStage.confirmDescription"),
      okText: t("productionStage.allowMedia"),
      cancelText: t("common.cancel"),
      onOk: () => confirmScript(current),
    });
  };
  return (
    <button
      type="button"
      disabled={busy || patching || !etag}
      className="btn-secondary"
      onClick={requestConfirmation}
    >
      {t("productionStage.confirmScript")}
    </button>
  );
}
