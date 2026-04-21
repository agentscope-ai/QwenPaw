/**
 * Shown when importing a zip whose ID already exists in the store (HTTP 409).
 * Presents the conflicting backup's metadata and lets the user choose to
 * replace it or cancel. The resolution is handled by useImportFlow.
 */
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import type { BackupMeta } from "@/api/types/backup";

interface Props {
  conflictMeta: BackupMeta | null;
  onChoice: () => void;
  onCancel: () => void;
}

export default function ImportConflictModal({
  conflictMeta,
  onChoice,
  onCancel,
}: Props) {
  const { t } = useTranslation();

  return (
    <Modal
      open={!!conflictMeta}
      title={t("backup.importConflictTitle")}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel")}
        </Button>,
        <Button key="replace" type="primary" danger onClick={() => onChoice()}>
          {t("backup.importReplace")}
        </Button>,
      ]}
    >
      <p>{t("backup.importConflictDesc")}</p>
      {conflictMeta && (
        <div
          style={{
            background: "var(--ant-color-fill-quaternary)",
            padding: 12,
            borderRadius: 6,
            marginTop: 8,
          }}
        >
          <div>
            <strong>{t("backup.name")}:</strong> {conflictMeta.name}
          </div>
          <div>
            <strong>ID:</strong>{" "}
            <span style={{ fontFamily: "monospace", fontSize: 12 }}>
              {conflictMeta.id}
            </span>
          </div>
          <div>
            <strong>{t("backup.createdAt")}:</strong>{" "}
            {dayjs(conflictMeta.created_at).format("YYYY-MM-DD HH:mm:ss")}
          </div>
        </div>
      )}
    </Modal>
  );
}
