import { Button, Empty, Input, Modal, Popconfirm, Skeleton, Tag, message } from "antd";
import { FileText } from "lucide-react";
import prettyBytes from "pretty-bytes";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../api/modules/chat";
import { personalLibraryApi } from "../../api/modules/personalLibrary";
import type { AttachmentListItem } from "../attachments/types";
import styles from "./PersonalWorkspaceNavigator.module.less";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import type { FileLocator } from "./fileLocator";

interface TemporaryAttachmentsPanelProps {
  onLibraryChanged?: () => void;
  requestContext: AgentRequestContext;
  onOpen?: (locator: FileLocator) => void;
}

export default function TemporaryAttachmentsPanel({onLibraryChanged, onOpen, requestContext}: TemporaryAttachmentsPanelProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<AttachmentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState<AttachmentListItem | null>(null);
  const [destinationPath, setDestinationPath] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    void chatApi
      .listAttachments({ lifecycle: "temporary", requestContext })
      .then((attachments) => {
        if (active) setItems(attachments);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [requestContext.agentId, requestContext.governance]);

  const openSaveDialog = (item: AttachmentListItem) => {
    setDestinationPath(`attachments/${item.original_name}`);
    setSaving(item);
  };

  const saveToLibrary = async () => {
    if (!saving || !destinationPath.trim()) return;
    setSubmitting(true);
    try {
      const document = await personalLibraryApi.copyAttachment({
        attachmentId: saving.id,
        destinationPath: destinationPath.trim(),
      }, requestContext);
      message.success(t("files.personalLibrary.copySucceeded", { path: document.relative_path }));
      setSaving(null);
      onLibraryChanged?.();
    } catch {
      message.error(t("files.personalLibrary.copyFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  const saveToAgentDocuments = async (item: AttachmentListItem) => {
    try {
      await chatApi.saveAttachment(item.id, undefined, requestContext);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      message.success(t("files.personalWorkspace.savedToDocuments"));
    } catch {
      message.error(t("files.personalWorkspace.operationFailed"));
    }
  };

  const remove = async (item: AttachmentListItem) => {
    try {
      await chatApi.deleteAttachment(item.id, requestContext);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
    } catch {
      message.error(t("files.personalWorkspace.operationFailed"));
    }
  };

  if (loading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }
  if (error) {
    return <Empty description={t("files.personalWorkspace.loadFailed")} />;
  }
  if (items.length === 0) {
    return <Empty description={t("files.personalWorkspace.noTemporary")} />;
  }

  return (
    <section className={styles.attachmentList} aria-label={t("files.personalWorkspace.temporary")}>
      <header className={styles.sectionHeading}>
        <div>
          <strong>{t("files.personalWorkspace.temporary")}</strong>
          <span>{t("files.personalWorkspace.temporaryDescription")}</span>
        </div>
        <Tag color="orange">{items.length}</Tag>
      </header>
      {items.map((item) => (
        <article key={item.id} className={styles.attachmentCard}>
          <span className={styles.fileIcon} aria-hidden="true">
            <FileText size={18} />
          </span>
          <div className={styles.attachmentBody}>
            <strong title={item.original_name}>{item.original_name}</strong>
            <span>
              {prettyBytes(item.size)} · {item.media_type}
            </span>
          </div>
          <Tag>{t("files.personalWorkspace.temporaryBadge")}</Tag>
          <Button size="small" disabled={!requestContext.agentId} onClick={() => requestContext.agentId && onOpen?.({category: "attachment", agentId: requestContext.agentId, stableId: item.id, relativePath: item.original_name, conversationId: item.conversation_id ?? undefined})}>查看</Button>
          <Button size="small" onClick={() => openSaveDialog(item)}>
            {t("files.personalLibrary.saveToLibrary")}
          </Button>
          <Button size="small" onClick={() => void saveToAgentDocuments(item)}>
            {t("files.personalWorkspace.saveToDocuments")}
          </Button>
          <Popconfirm title={t("files.personalWorkspace.deleteAttachmentConfirm")} onConfirm={() => void remove(item)}>
            <Button size="small" danger>{t("common.delete")}</Button>
          </Popconfirm>
        </article>
      ))}
      <Modal
        title={t("files.personalLibrary.saveToLibrary")}
        open={saving !== null}
        onCancel={() => setSaving(null)}
        onOk={() => void saveToLibrary()}
        okButtonProps={{ loading: submitting, disabled: !destinationPath.trim() }}
        okText={t("common.confirm")}
      >
        <p>{t("files.personalLibrary.sourceUnchanged")}</p>
        <Input
          aria-label={t("files.personalLibrary.destinationPath")}
          value={destinationPath}
          onChange={(event) => setDestinationPath(event.target.value)}
        />
      </Modal>
    </section>
  );
}
