import { Alert, Button, Empty, List, Skeleton, Typography, message } from "antd";
import { FileText, LibraryBig, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  personalLibraryApi,
  type PersonalLibraryDocument,
} from "../../api/modules/personalLibrary";
import styles from "./PersonalWorkspaceNavigator.module.less";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import type { FileLocator } from "./fileLocator";

interface PersonalLibraryPanelProps {
  refreshToken?: number;
  requestContext: AgentRequestContext;
  onOpen?: (locator: FileLocator) => void;
}

export default function PersonalLibraryPanel({refreshToken = 0, requestContext, onOpen}: PersonalLibraryPanelProps) {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<PersonalLibraryDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadRevision, setLoadRevision] = useState(0);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const loadSequence = useRef(0);

  const load = async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setDocuments([]);
    setLoadFailed(false);
    try {
      const result = await personalLibraryApi.list("", requestContext);
      if (sequence === loadSequence.current) setDocuments(result);
    } catch {
      if (sequence === loadSequence.current) setLoadFailed(true);
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      loadSequence.current += 1;
    };
  }, [refreshToken, loadRevision, requestContext.agentId, requestContext.governance]);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      await personalLibraryApi.upload(file, requestContext);
      message.success(t("files.personalLibrary.uploadSucceeded", { name: file.name }));
      await load();
    } catch (error) {
      const detail = error instanceof Error && error.message.includes("library_document_exists")
        ? t("files.personalLibrary.uploadConflict")
        : error instanceof Error ? error.message : t("files.personalLibrary.uploadFailed");
      message.error(detail);
    } finally {
      setUploading(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
    }
  };

  return (
    <section className={styles.libraryPanel} aria-label={t("files.personalLibrary.title")}>
      <header className={styles.sectionHeading}>
        <div>
          <strong>{t("files.personalLibrary.title")}</strong>
          <span>{t("files.personalLibrary.description")}</span>
        </div>
        <div>
          <input
            ref={uploadInputRef}
            type="file"
            aria-label={t("files.personalLibrary.upload")}
            hidden
            onChange={(event) => {
              const [file] = Array.from(event.target.files ?? []);
              if (file) void upload(file);
            }}
          />
          <Button
            type="primary"
            icon={<Upload size={16} />}
            loading={uploading}
            onClick={() => uploadInputRef.current?.click()}
          >
            {t("files.personalLibrary.upload")}
          </Button>
        </div>
      </header>
      {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : loadFailed ? (
        <Alert type="error" showIcon message={t("files.personalLibrary.loadFailed")} action={<Button onClick={() => setLoadRevision((value) => value + 1)}>{t("files.personalLibrary.retry")}</Button>} />
      ) : documents.length === 0 ? (
        <Empty image={<LibraryBig size={44} />} description={t("files.personalLibrary.empty")} />
      ) : (
        <List
          dataSource={documents}
          renderItem={(document) => (
            <List.Item>
              <List.Item.Meta
                avatar={<FileText size={18} />}
                title={<Button type="link" disabled={!requestContext.agentId} onClick={() => requestContext.agentId && onOpen?.({category: "library", agentId: requestContext.agentId, stableId: document.id, relativePath: document.relative_path})}>{document.name}</Button>}
                description={<Typography.Text type="secondary">{document.relative_path}</Typography.Text>}
              />
            </List.Item>
          )}
        />
      )}
    </section>
  );
}
