import {
  Alert,
  Button,
  Empty,
  Input,
  List,
  Modal,
  Pagination,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { FileText, LibraryBig, RefreshCw, Upload } from "lucide-react";
import prettyBytes from "pretty-bytes";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "../../api/authSession";
import {
  personalLibraryApi,
  type PersonalLibraryDocument,
  type PersonalLibraryIndexStatus,
} from "../../api/modules/personalLibrary";
import { ApiRequestError } from "../../api/request";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import type { FileLocator } from "./fileLocator";
import styles from "./PersonalWorkspaceNavigator.module.less";

interface PersonalLibraryPanelProps {
  refreshToken?: number;
  requestContext: AgentRequestContext;
  onOpen?: (locator: FileLocator) => void;
  onDocumentChanged?: (
    id: string,
    document: PersonalLibraryDocument | null,
  ) => void;
}

type ManagementAction = "rename" | "move" | "delete";
const PAGE_SIZE = 20;

export default function PersonalLibraryPanel(props: PersonalLibraryPanelProps) {
  const generation = useSyncExternalStore(
    subscribeAccessSessionGeneration,
    getAccessSessionGeneration,
  );
  // A scope change discards dialogs, rows, pagination and pending UI callbacks.
  return (
    <LibraryContents
      key={JSON.stringify([
        generation,
        props.requestContext.agentId,
        props.requestContext.governance,
      ])}
      {...props}
    />
  );
}

function LibraryContents({
  refreshToken = 0,
  requestContext,
  onOpen,
  onDocumentChanged,
}: PersonalLibraryPanelProps) {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<PersonalLibraryDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  const [indexStatuses, setIndexStatuses] = useState<
    PersonalLibraryIndexStatus[]
  >([]);
  const [indexFailed, setIndexFailed] = useState(false);
  const [rebuildProgress, setRebuildProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const rebuildController = useRef<AbortController>();
  const [editing, setEditing] = useState<{
    action: ManagementAction;
    document: PersonalLibraryDocument;
  } | null>(null);
  const [destination, setDestination] = useState("");
  const [operationError, setOperationError] = useState("");
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const active = useRef(true);
  const pending = useRef(false);
  const generation = getAccessSessionGeneration();
  const current = () =>
    active.current && generation === getAccessSessionGeneration();

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      rebuildController.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setDocuments([]);
    setLoadFailed(false);
    void personalLibraryApi
      .listPage(
        query,
        (page - 1) * PAGE_SIZE,
        PAGE_SIZE,
        requestContext,
        controller.signal,
      )
      .then((result) => {
        if (controller.signal.aborted || !current()) return;
        const lastPage = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
        if (page > lastPage) {
          setPage(lastPage);
          return;
        }
        setDocuments(result.items);
        setTotal(result.total);
      })
      .catch(() => {
        if (!controller.signal.aborted && current()) setLoadFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted && current()) setLoading(false);
      });
    return () => controller.abort();
  }, [
    query,
    page,
    refreshToken,
    revision,
    requestContext.agentId,
    requestContext.governance,
  ]);

  useEffect(() => {
    let cancelled = false;
    setIndexStatuses([]);
    setIndexFailed(false);
    void personalLibraryApi
      .indexStatus(requestContext)
      .then((result) => {
        if (!cancelled && current()) setIndexStatuses(result);
      })
      .catch(() => {
        if (!cancelled && current()) setIndexFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [
    refreshToken,
    revision,
    requestContext.agentId,
    requestContext.governance,
  ]);

  const rebuild = async () => {
    if (pending.current || !current()) return;
    const controller = new AbortController();
    rebuildController.current = controller;
    pending.current = true;
    setBusy(true);
    setRebuildProgress({ done: 0, total });
    try {
      // Pagination and search only affect display; rebuild still covers the whole library.
      const files = await personalLibraryApi.list("", requestContext);
      if (!current() || controller.signal.aborted) return;
      setRebuildProgress({ done: 0, total: files.length });
      let result: PersonalLibraryIndexStatus[] = [];
      for (let offset = 0; offset < files.length; offset += 5) {
        result = await personalLibraryApi.rebuildIndex(
          files.slice(offset, offset + 5).map((file) => file.id),
          requestContext,
          controller.signal,
        );
        if (!current() || controller.signal.aborted) return;
        setIndexStatuses(result);
        setIndexFailed(false);
        setRebuildProgress({
          done: Math.min(offset + 5, files.length),
          total: files.length,
        });
      }
      if (result.some((item) => item.status !== "ready"))
        message.warning(t("files.personalLibrary.index.rebuildIncomplete"));
      else message.success(t("files.personalLibrary.index.rebuilt"));
    } catch {
      if (current() && !controller.signal.aborted)
        message.error(t("files.personalLibrary.index.rebuildFailed"));
    } finally {
      pending.current = false;
      if (current()) {
        setBusy(false);
        setRebuildProgress(null);
      }
    }
  };

  const failureMessage = (error: unknown, fallback: string) => {
    const detail = error instanceof Error ? error.message : "";
    if (detail.includes("library_document_exists"))
      return t("files.personalLibrary.uploadConflict");
    if (detail.includes("library_document_changed"))
      return t("files.personalLibrary.changed");
    if (
      detail.includes("invalid_library") ||
      detail.includes("library_symlink_denied")
    )
      return t("files.personalLibrary.invalidPath");
    if (
      error instanceof ApiRequestError &&
      (error.status === 403 || error.status === 404)
    )
      return t("files.personalLibrary.unavailable");
    return t(fallback);
  };

  const upload = async (file: File) => {
    if (pending.current || !current()) return;
    pending.current = true;
    setBusy(true);
    try {
      await personalLibraryApi.upload(file, requestContext);
      if (!current()) return;
      message.success(
        t("files.personalLibrary.uploadSucceeded", { name: file.name }),
      );
      setRevision((value) => value + 1);
    } catch (error) {
      if (current())
        message.error(
          failureMessage(error, "files.personalLibrary.uploadFailed"),
        );
    } finally {
      pending.current = false;
      if (current()) {
        setBusy(false);
        if (uploadInputRef.current) uploadInputRef.current.value = "";
      }
    }
  };

  const openAction = (
    action: ManagementAction,
    document: PersonalLibraryDocument,
  ) => {
    setEditing({ action, document });
    setDestination(
      action === "rename" ? document.name : document.relative_path,
    );
    setOperationError("");
  };

  const submit = async () => {
    if (!editing || pending.current || !current()) return;
    const { action, document } = editing;
    const value = destination.trim();
    if (
      action !== "delete" &&
      (!value || (action === "rename" && /[/\\]/.test(value)))
    ) {
      setOperationError(t("files.personalLibrary.invalidPath"));
      return;
    }
    const parent = document.relative_path.slice(
      0,
      document.relative_path.lastIndexOf("/") + 1,
    );
    pending.current = true;
    setBusy(true);
    setOperationError("");
    try {
      const changed =
        action === "delete"
          ? (await personalLibraryApi.remove(document, requestContext), null)
          : await personalLibraryApi.move(
              document,
              action === "rename" ? parent + value : value,
              requestContext,
            );
      if (!current()) return;
      setEditing(null);
      onDocumentChanged?.(document.id, changed);
      setRevision((previous) => previous + 1);
      message.success(t("files.personalLibrary.operationSucceeded"));
    } catch (error) {
      if (current())
        setOperationError(
          failureMessage(error, "files.personalLibrary.operationFailed"),
        );
    } finally {
      pending.current = false;
      if (current()) setBusy(false);
    }
  };

  return (
    <section
      className={styles.libraryPanel}
      aria-label={t("files.personalLibrary.title")}
    >
      <header className={styles.sectionHeading}>
        <div>
          <strong>{t("files.personalLibrary.title")}</strong>
          <span>{t("files.personalLibrary.description")}</span>
        </div>
        <div>
          <Button
            icon={<RefreshCw size={16} />}
            loading={rebuildProgress !== null}
            disabled={loading || busy || total === 0}
            onClick={() => void rebuild()}
          >
            {rebuildProgress === null
              ? t("files.personalLibrary.index.rebuild")
              : t("files.personalLibrary.index.progress", rebuildProgress)}
          </Button>
          <input
            ref={uploadInputRef}
            type="file"
            aria-label={t("files.personalLibrary.upload")}
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <Button
            type="primary"
            icon={<Upload size={16} />}
            loading={busy && !editing && rebuildProgress === null}
            disabled={busy || !requestContext.agentId}
            onClick={() => uploadInputRef.current?.click()}
          >
            {t("files.personalLibrary.upload")}
          </Button>
        </div>
      </header>
      <div className={styles.libraryToolbar}>
        <Input.Search
          allowClear
          maxLength={256}
          placeholder={t("files.personalLibrary.search")}
          aria-label={t("files.personalLibrary.search")}
          onSearch={(value) => {
            setQuery(value.trim());
            setPage(1);
          }}
        />
        <Button
          disabled={busy}
          onClick={() => setRevision((value) => value + 1)}
        >
          {t("files.personalLibrary.refresh")}
        </Button>
      </div>
      {indexFailed && (
        <Alert
          type="warning"
          showIcon
          message={t("files.personalLibrary.index.loadFailed")}
          action={
            <Button onClick={() => setRevision((value) => value + 1)}>
              {t("files.personalLibrary.retry")}
            </Button>
          }
        />
      )}
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : loadFailed ? (
        <Alert
          type="error"
          showIcon
          message={t("files.personalLibrary.loadFailed")}
          action={
            <Button onClick={() => setRevision((value) => value + 1)}>
              {t("files.personalLibrary.retry")}
            </Button>
          }
        />
      ) : documents.length === 0 ? (
        <Empty
          image={<LibraryBig size={44} />}
          description={t(
            query
              ? "files.personalLibrary.noMatches"
              : "files.personalLibrary.empty",
          )}
        />
      ) : (
        <List
          dataSource={documents}
          rowKey="id"
          renderItem={(document) => {
            const index = indexStatuses.find(
              (item) => item.document_id === document.id,
            );
            const state = indexFailed
              ? "unavailable"
              : index?.status ?? "pending";
            return (
              <List.Item className={styles.libraryRow}>
                <List.Item.Meta
                  avatar={<FileText size={18} />}
                  title={
                    <Button
                      type="link"
                      disabled={!requestContext.agentId}
                      onClick={() =>
                        requestContext.agentId &&
                        onOpen?.({
                          category: "library",
                          agentId: requestContext.agentId,
                          stableId: document.id,
                          relativePath: document.relative_path,
                        })
                      }
                    >
                      {document.name}
                    </Button>
                  }
                  description={
                    <>
                      <Typography.Text type="secondary">
                        {document.relative_path}
                      </Typography.Text>
                      <br />
                      <Typography.Text type="secondary">
                        {prettyBytes(document.size ?? 0)}
                      </Typography.Text>{" "}
                      <Tooltip
                        title={t(`files.personalLibrary.index.help.${state}`)}
                      >
                        <Tag
                          color={
                            state === "ready"
                              ? "green"
                              : state === "pending"
                              ? "default"
                              : "orange"
                          }
                        >
                          {t(`files.personalLibrary.index.status.${state}`)}
                        </Tag>
                      </Tooltip>
                    </>
                  }
                />
                <Space wrap size="small">
                  {(["rename", "move", "delete"] as const).map((action) => (
                    <Button
                      key={action}
                      size="small"
                      danger={action === "delete"}
                      disabled={busy}
                      onClick={() => openAction(action, document)}
                    >
                      {t("files.personalLibrary." + action)}
                    </Button>
                  ))}
                </Space>
              </List.Item>
            );
          }}
        />
      )}
      {!loadFailed && total > 0 && (
        <Pagination
          className={styles.libraryPagination}
          current={page}
          total={total}
          pageSize={PAGE_SIZE}
          showSizeChanger={false}
          disabled={loading || busy}
          onChange={setPage}
          showTotal={(count) => t("files.personalLibrary.total", { count })}
        />
      )}
      <Modal
        open={editing !== null}
        title={editing ? t("files.personalLibrary." + editing.action) : ""}
        onCancel={() => !busy && setEditing(null)}
        onOk={() => void submit()}
        confirmLoading={busy}
        closable={!busy}
        maskClosable={!busy}
        cancelButtonProps={{ disabled: busy }}
        okButtonProps={{ danger: editing?.action === "delete" }}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
      >
        <p>{editing?.document.relative_path}</p>
        {editing?.action === "delete" ? (
          <Alert
            showIcon
            type="warning"
            message={t("files.personalLibrary.deleteConfirm")}
          />
        ) : (
          <>
            <p>
              {t(
                editing?.action === "rename"
                  ? "files.personalLibrary.renameHint"
                  : "files.personalLibrary.moveHint",
              )}
            </p>
            <Input
              aria-label={t("files.personalLibrary.destinationPath")}
              value={destination}
              maxLength={1024}
              disabled={busy}
              onChange={(event) => setDestination(event.target.value)}
              onPressEnter={() => void submit()}
            />
          </>
        )}
        {operationError && (
          <Alert
            style={{ marginTop: 12 }}
            type="error"
            showIcon
            message={operationError}
          />
        )}
      </Modal>
    </section>
  );
}
