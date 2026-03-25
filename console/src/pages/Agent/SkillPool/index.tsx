import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Input,
  Modal,
  Tooltip,
  message,
  Drawer,
  Form,
} from "@agentscope-ai/design";
import {
  CheckOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  ImportOutlined,
  PlusOutlined,
  SyncOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type { PoolSkillSpec, WorkspaceSkillSummary } from "../../../api/types";
import { parseErrorDetail } from "../../../utils/error";
import {
  getSkillDisplaySource,
  getSkillVisual,
  parseFrontmatter,
  isSupportedSkillUrl,
  SUPPORTED_SKILL_URL_PREFIXES,
} from "../Skills/components";
import { MarkdownCopy } from "../../../components/MarkdownCopy/MarkdownCopy";
import styles from "../Skills/index.module.less";

type PoolMode = "upload" | "download" | "create" | "edit";
type FetchLatestResult = Awaited<
  ReturnType<typeof api.fetchLatestSkillPoolBuiltins>
>;

function SkillPoolPage() {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<PoolSkillSpec[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [mode, setMode] = useState<PoolMode | null>(null);
  const [activeSkill, setActiveSkill] = useState<PoolSkillSpec | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string>();
  const [workspaceSkillName, setWorkspaceSkillName] = useState<string>();
  const [targetWorkspaceIds, setTargetWorkspaceIds] = useState<string[]>([]);
  const [rename, setRename] = useState("");
  const [name, setName] = useState("");
  const [configText, setConfigText] = useState("{}");
  const zipInputRef = useRef<HTMLInputElement>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const [importing, setImporting] = useState(false);

  // Form state for create/edit drawer
  const [form] = Form.useForm();
  const [drawerContent, setDrawerContent] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [poolSkills, workspaceSummaries] = await Promise.all([
        api.listSkillPoolSkills(),
        api.listSkillWorkspaces(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSummaries);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to load skill pool",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const closeModal = () => {
    setMode(null);
    setActiveSkill(null);
    setWorkspaceId(undefined);
    setWorkspaceSkillName(undefined);
    setTargetWorkspaceIds([]);
    setRename("");
    setName("");
    setConfigText("{}");
  };

  const openCreate = () => {
    setMode("create");
    setName("");
    setDrawerContent("");
    setConfigText("{}");
    form.resetFields();
    form.setFieldsValue({
      name: "",
      content: "",
    });
  };

  const openDownload = (skill?: PoolSkillSpec) => {
    setMode("download");
    setActiveSkill(skill || null);
    setTargetWorkspaceIds([]);
    setRename("");
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
    setImportUrl("");
    setImportUrlError("");
  };

  const openEdit = (skill: PoolSkillSpec) => {
    setMode("edit");
    setActiveSkill(skill);
    setName(skill.protected ? `${skill.name}_custom` : skill.name);
    setDrawerContent(skill.content);
    setConfigText(JSON.stringify(skill.config || {}, null, 2));
    form.setFieldsValue({
      name: skill.name,
      content: skill.content,
    });
  };

  const closeDrawer = () => {
    setMode(null);
    setActiveSkill(null);
  };

  const handleDrawerContentChange = (content: string) => {
    setDrawerContent(content);
    form.setFieldsValue({ content });
  };

  const validateFrontmatter = useCallback(
    (_: unknown, value: string) => {
      const content = drawerContent || value;
      if (!content || !content.trim()) {
        return Promise.reject(new Error(t("skills.pleaseInputContent")));
      }
      const fm = parseFrontmatter(content);
      if (!fm) {
        return Promise.reject(new Error(t("skills.frontmatterRequired")));
      }
      if (!fm.name) {
        return Promise.reject(new Error(t("skills.frontmatterNameRequired")));
      }
      if (!fm.description) {
        return Promise.reject(
          new Error(t("skills.frontmatterDescriptionRequired")),
        );
      }
      return Promise.resolve();
    },
    [drawerContent, t],
  );

  const handleUpload = async () => {
    if (!workspaceId || !workspaceSkillName) return;
    try {
      await api.uploadWorkspaceSkillToPool({
        workspace_id: workspaceId,
        skill_name: workspaceSkillName,
        new_name: rename.trim() || undefined,
      });
      message.success(t("skillPool.uploadedToPool"));
      closeModal();
      await loadData();
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        setRename(detail.suggested_name);
        message.warning(t("skillPool.nameConflict"));
        return;
      }
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  const handleDownload = async () => {
    if (!activeSkill || targetWorkspaceIds.length === 0) return;
    const allSelected = targetWorkspaceIds.includes("__all__");
    try {
      await api.downloadSkillPoolSkill({
        skill_name: activeSkill.name,
        all_workspaces: allSelected,
        targets: allSelected
          ? []
          : targetWorkspaceIds.map((workspace_id) => ({
              workspace_id,
              target_name: rename.trim() || undefined,
            })),
      });
      message.success(t("skills.downloadedToWorkspace"));
      closeModal();
      await loadData();
    } catch (error) {
      const detail = parseErrorDetail(error);
      const conflicts = Array.isArray(detail?.conflicts)
        ? detail.conflicts
        : [];
      const conflict = conflicts[0];
      if (conflict?.suggested_name) {
        setRename(conflict.suggested_name);
        const conflictNames = conflicts
          .map((item) => item.workspace_id || item.suggested_name)
          .join(", ");
        message.warning(`${t("skillPool.nameConflict")}: ${conflictNames}`);
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("common.download") + " failed",
      );
    }
  };

  const handleSavePoolSkill = async () => {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;

    const trimmedConfig = configText.trim();
    let parsedConfig: Record<string, unknown> = {};
    if (trimmedConfig && trimmedConfig !== "{}") {
      try {
        parsedConfig = JSON.parse(trimmedConfig);
      } catch {
        message.error(t("skills.configInvalidJson"));
        return;
      }
    }

    const skillName = name.trim() || values.name;
    const skillContent = drawerContent || values.content;

    if (!skillName.trim() || !skillContent.trim()) return;

    try {
      const result =
        mode === "edit"
          ? await api.saveSkillPoolSkill({
              name: skillName,
              content: skillContent,
              source_name: activeSkill?.name,
              config: parsedConfig,
            })
          : await api
              .createSkillPoolSkill({
                name: skillName,
                content: skillContent,
                config: parsedConfig,
              })
              .then((created) => ({
                success: true,
                mode: "edit" as const,
                name: created.name,
              }));
      message.success(
        mode === "edit" && result.mode === "fork"
          ? `${t("common.create")}: ${result.name}`
          : mode === "edit"
          ? t("common.save")
          : t("common.create"),
      );
      closeDrawer();
      await loadData();
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        setName(detail.suggested_name);
        message.warning(t("skillPool.nameConflict"));
        return;
      }
      message.error(
        error instanceof Error ? error.message : t("common.save") + " failed",
      );
    }
  };

  const handleDelete = async (skill: PoolSkillSpec) => {
    Modal.confirm({
      title: t("skillPool.deleteTitle", { name: skill.name }),
      content: skill.protected
        ? t("skillPool.deleteProtected")
        : t("skillPool.deleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      onOk: async () => {
        if (skill.protected) return;
        await api.deleteSkillPoolSkill(skill.name);
        message.success(t("skillPool.deletedFromPool"));
        await loadData();
      },
    });
  };

  const handleFetchLatest = async (
    approveConflicts: boolean = false,
    previewOnly: boolean = false,
  ) => {
    setSyncing(true);
    try {
      const result: FetchLatestResult = await api.fetchLatestSkillPoolBuiltins(
        approveConflicts,
        previewOnly,
      );
      if (previewOnly && !approveConflicts) {
        const additions = Array.isArray(result.additions)
          ? result.additions
          : [];
        const updates = Array.isArray(result.updates) ? result.updates : [];
        const conflicts = Array.isArray(result.conflicts)
          ? result.conflicts
          : [];
        if (!additions.length && !updates.length && !conflicts.length) {
          message.info(t("skillPool.upToDate"));
          return;
        }
        Modal.confirm({
          title: t("skillPool.builtinConflicts"),
          content: (
            <div>
              {additions.length ? (
                <div style={{ marginBottom: 8 }}>
                  {t("skillPool.previewAdditions", {
                    names: additions.join(", "),
                  })}
                </div>
              ) : null}
              {updates.length ? (
                <div style={{ marginBottom: 8 }}>
                  {t("skillPool.previewUpdates", {
                    names: updates.join(", "),
                  })}
                </div>
              ) : null}
              {conflicts.map((item) => (
                <div key={item.skill_name}>
                  {t("skillPool.previewConflicts", {
                    skill: item.skill_name,
                    suggested: item.suggested_name,
                  })}
                </div>
              ))}
            </div>
          ),
          okText: t("skillPool.approve"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await handleFetchLatest(true, false);
          },
        });
        return;
      }
      if (result.synced?.length) {
        message.success(
          t("skillPool.synced", { names: result.synced.join(", ") }),
        );
      } else {
        message.info(t("skillPool.upToDate"));
      }
      await loadData();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skillPool.syncFailed"),
      );
    } finally {
      setSyncing(false);
    }
  };

  const handleZipImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    try {
      const result = await api.uploadSkillPoolZip(file, { overwrite: false });
      if (result.count > 0) {
        message.success(
          t("skillPool.imported", { names: result.imported.join(", ") }),
        );
      } else {
        message.info(t("skillPool.noNewImports"));
      }
      await loadData();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skillPool.zipImportFailed"),
      );
    }
  };

  const handleImportUrlChange = (value: string) => {
    setImportUrl(value);
    const trimmed = value.trim();
    if (trimmed && !isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    setImportUrlError("");
  };

  const handleConfirmImport = async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (!isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource"));
      return;
    }
    try {
      setImporting(true);
      const result = await api.importPoolSkillFromHub({
        bundle_url: trimmed,
        overwrite: false,
      });
      message.success(`${t("common.create")}: ${result.name}`);
      closeImportModal();
      await loadData();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("nav.skillPool")}</h1>
          <p className={styles.description}>{t("skillPool.description")}</p>
        </div>
        <div className={styles.headerActions}>
          <input
            type="file"
            accept=".zip"
            ref={zipInputRef}
            onChange={handleZipImport}
            style={{ display: "none" }}
          />
          <div className={styles.headerActionsLeft}>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="primary"
                className={styles.primaryTransferButton}
                icon={<CloudUploadOutlined />}
                onClick={() => setMode("upload")}
              >
                {t("skillPool.upload")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.downloadFromPoolHint")}>
              <Button
                type="primary"
                className={styles.primaryTransferButton}
                icon={<DownloadOutlined />}
                onClick={() => openDownload()}
              >
                {t("skillPool.download")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skillPool.fetchLatestHint")}>
              <Button
                type="primary"
                className={styles.primaryTransferButton}
                icon={<SyncOutlined />}
                loading={syncing}
                onClick={() => void handleFetchLatest(false, true)}
              >
                {t("skillPool.fetchLatest")}
              </Button>
            </Tooltip>
          </div>
          <div className={styles.headerActionsRight}>
            <Button
              type="default"
              className={styles.creationActionButton}
              icon={<UploadOutlined />}
              onClick={() => zipInputRef.current?.click()}
            >
              {t("skills.uploadSkill")}
            </Button>
            <Button
              type="default"
              className={styles.creationActionButton}
              icon={<ImportOutlined />}
              onClick={() => setImportModalOpen(true)}
            >
              {t("skills.importSkills")}
            </Button>
            <Button
              type="default"
              className={styles.creationActionButton}
              icon={<PlusOutlined />}
              onClick={openCreate}
            >
              {t("skills.createSkill")}
            </Button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {skills.map((skill) => (
            <Card key={skill.name} className={styles.skillCard}>
              <div className={styles.cardBody}>
                <div className={styles.cardHeader}>
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span className={styles.fileIcon}>
                      {getSkillVisual(skill.name, skill.content)}
                    </span>
                    <h3 className={styles.skillTitle}>{skill.name}</h3>
                  </div>
                  <span
                    className={
                      skill.protected ? styles.builtinTag : styles.customizedTag
                    }
                  >
                    {getSkillDisplaySource(skill.source)}
                  </span>
                </div>
                <div className={styles.descriptionSection}>
                  <div className={styles.infoLabel}>
                    {t("skillPool.descriptionLabel")}
                  </div>
                  <div
                    className={`${styles.infoBlock} ${styles.descriptionContent}`}
                  >
                    {skill.description || "-"}
                  </div>
                </div>
                <div className={styles.metaStack}>
                  <div className={styles.infoSection}>
                    <div className={styles.infoLabel}>
                      {t("skillPool.version")}
                    </div>
                    <div className={styles.infoBlock}>
                      {skill.version_text || skill.commit_text || "-"}
                    </div>
                  </div>
                  <div className={styles.infoSection}>
                    <div className={styles.infoLabel}>
                      {t("skillPool.path")}
                    </div>
                    <div className={`${styles.infoBlock} ${styles.pathValue}`}>
                      {skill.path}
                    </div>
                  </div>
                </div>
              </div>
              <div className={styles.cardFooter}>
                <Button
                  type="link"
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={() => {
                    openDownload(skill);
                  }}
                >
                  {t("skillPool.download")}
                </Button>
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => openEdit(skill)}
                >
                  {t("skillPool.edit")}
                </Button>
                <Button
                  type="link"
                  size="small"
                  danger
                  disabled={skill.protected}
                  icon={<DeleteOutlined />}
                  onClick={() => void handleDelete(skill)}
                >
                  {t("skillPool.delete")}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        title={`${t("skills.importSkills")} Hub`}
        open={importModalOpen}
        onCancel={closeImportModal}
        keyboard={!importing}
        closable={!importing}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={closeImportModal} style={{ marginRight: 8 }}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              onClick={handleConfirmImport}
              loading={importing}
              disabled={importing || !importUrl.trim() || !!importUrlError}
            >
              {t("skills.importSkills")}
            </Button>
          </div>
        }
        width={760}
      >
        <div className={styles.importHintBlock}>
          <p className={styles.importHintTitle}>
            {t("skillPool.externalHubHint")}
          </p>
          <p className={styles.importHintTitle}>
            {t("skills.supportedSkillUrlSources")}
          </p>
          <ul className={styles.importHintList}>
            {SUPPORTED_SKILL_URL_PREFIXES.map((url) => (
              <li key={url}>{url}</li>
            ))}
          </ul>
          <p className={styles.importHintTitle}>{t("skills.urlExamples")}</p>
          <ul className={styles.importHintList}>
            <li>https://skills.sh/vercel-labs/skills/find-skills</li>
            <li>https://lobehub.com/zh/skills/openclaw-skills-cli-developer</li>
            <li>
              https://market.lobehub.com/api/v1/skills/openclaw-skills-cli-developer/download
            </li>
            <li>
              https://github.com/anthropics/skills/tree/main/skills/skill-creator
            </li>
            <li>https://modelscope.cn/skills/@anthropics/skill-creator</li>
          </ul>
        </div>

        <input
          className={styles.importUrlInput}
          value={importUrl}
          onChange={(e) => handleImportUrlChange(e.target.value)}
          placeholder={t("skills.enterSkillUrl")}
          disabled={importing}
        />
        {importUrlError ? (
          <div className={styles.importUrlError}>{importUrlError}</div>
        ) : null}
        {importing ? (
          <div className={styles.importLoadingText}>{t("common.loading")}</div>
        ) : null}
      </Modal>

      <Modal
        open={mode === "upload" || mode === "download"}
        onCancel={closeModal}
        onOk={mode === "upload" ? handleUpload : handleDownload}
        okButtonProps={{
          disabled:
            mode === "upload"
              ? !workspaceId || !workspaceSkillName
              : !activeSkill || targetWorkspaceIds.length === 0,
        }}
        title={
          mode === "upload"
            ? t("skillPool.uploadToPool")
            : t("skillPool.downloadTitle", { name: activeSkill?.name || "" })
        }
        width={640}
      >
        <div style={{ display: "grid", gap: 8 }}>
          {mode === "upload" ? (
            !workspaceId ? (
              <>
                <div className={styles.pickerLabel}>
                  {t("skillPool.selectWorkspace")}
                </div>
                <div className={styles.pickerGrid}>
                  {workspaces.map((ws) => (
                    <div
                      key={ws.agent_id}
                      className={styles.pickerCard}
                      onClick={() => {
                        setWorkspaceId(ws.agent_id);
                        setWorkspaceSkillName(undefined);
                      }}
                    >
                      <div className={styles.pickerCardTitle}>
                        {ws.agent_id}
                      </div>
                      <div className={styles.pickerCardMeta}>
                        {t("skillPool.skillCount", {
                          count: ws.skills.length,
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <span
                  className={styles.pickerBack}
                  onClick={() => {
                    setWorkspaceId(undefined);
                    setWorkspaceSkillName(undefined);
                  }}
                >
                  {"← "}
                  {t("skillPool.back")}
                </span>
                <div className={styles.pickerLabel}>
                  {t("skillPool.selectWorkspaceSkill")}
                </div>
                <div className={styles.pickerGrid}>
                  {(
                    workspaces.find((w) => w.agent_id === workspaceId)
                      ?.skills || []
                  ).map((skill) => {
                    const sel = workspaceSkillName === skill.name;
                    return (
                      <div
                        key={skill.name}
                        className={`${styles.pickerCard} ${
                          sel ? styles.pickerCardSelected : ""
                        }`}
                        onClick={() => setWorkspaceSkillName(skill.name)}
                      >
                        {sel && (
                          <span className={styles.pickerCheck}>
                            <CheckOutlined />
                          </span>
                        )}
                        <div className={styles.pickerCardTitle}>
                          {skill.name}
                        </div>
                        <div className={styles.pickerCardMeta}>
                          {skill.sync_to_pool?.status || "not_sync"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )
          ) : (
            <>
              {!activeSkill ? (
                <>
                  <div className={styles.pickerLabel}>
                    {t("skills.selectPoolItem")}
                  </div>
                  <div className={styles.pickerGrid}>
                    {skills.map((skill) => (
                      <div
                        key={skill.name}
                        className={styles.pickerCard}
                        onClick={() => setActiveSkill(skill)}
                      >
                        <div className={styles.pickerCardTitle}>
                          {skill.name}
                        </div>
                        <div className={styles.pickerCardMeta}>
                          {skill.version_text ||
                            skill.commit_text ||
                            skill.source}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <span
                    className={styles.pickerBack}
                    onClick={() => {
                      setActiveSkill(null);
                      setTargetWorkspaceIds([]);
                    }}
                  >
                    {"← "}
                    {t("skillPool.back")}
                  </span>
                  <div className={styles.pickerLabel}>
                    {t("skillPool.selectWorkspaces")}
                  </div>
                  <div className={styles.pickerGrid}>
                    <div
                      className={`${styles.pickerCard} ${
                        styles.pickerAllCard
                      } ${
                        targetWorkspaceIds.includes("__all__")
                          ? styles.pickerCardSelected
                          : ""
                      }`}
                      onClick={() => setTargetWorkspaceIds(["__all__"])}
                    >
                      {targetWorkspaceIds.includes("__all__") && (
                        <span className={styles.pickerCheck}>
                          <CheckOutlined />
                        </span>
                      )}
                      <div className={styles.pickerCardTitle}>
                        {t("skillPool.allWorkspaces")}
                      </div>
                    </div>
                    {workspaces.map((ws) => {
                      const sel =
                        !targetWorkspaceIds.includes("__all__") &&
                        targetWorkspaceIds.includes(ws.agent_id);
                      return (
                        <div
                          key={ws.agent_id}
                          className={`${styles.pickerCard} ${
                            sel ? styles.pickerCardSelected : ""
                          }`}
                          onClick={() => {
                            if (targetWorkspaceIds.includes("__all__")) {
                              setTargetWorkspaceIds([ws.agent_id]);
                            } else if (sel) {
                              setTargetWorkspaceIds(
                                targetWorkspaceIds.filter(
                                  (id) => id !== ws.agent_id,
                                ),
                              );
                            } else {
                              setTargetWorkspaceIds([
                                ...targetWorkspaceIds,
                                ws.agent_id,
                              ]);
                            }
                          }}
                        >
                          {sel && (
                            <span className={styles.pickerCheck}>
                              <CheckOutlined />
                            </span>
                          )}
                          <div className={styles.pickerCardTitle}>
                            {ws.agent_id}
                          </div>
                          <div className={styles.pickerCardMeta}>
                            {t("skillPool.skillCount", {
                              count: ws.skills.length,
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </>
          )}
          <Input
            value={rename}
            onChange={(e) => setRename(e.target.value)}
            placeholder={t("skillPool.optionalRename")}
          />
        </div>
      </Modal>

      <Drawer
        width={520}
        placement="right"
        title={
          mode === "edit"
            ? t("skillPool.editTitle", { name: activeSkill?.name || "" })
            : t("skillPool.createTitle")
        }
        open={mode === "create" || mode === "edit"}
        onClose={closeDrawer}
        destroyOnClose
        footer={
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={closeDrawer}>{t("common.cancel")}</Button>
            <Button type="primary" onClick={handleSavePoolSkill}>
              {mode === "edit" ? t("common.save") : t("common.create")}
            </Button>
          </div>
        }
      >
        <Form form={form} layout="vertical" onFinish={handleSavePoolSkill}>
          <Form.Item
            name="name"
            label={t("skillPool.skillName")}
            rules={[{ required: true, message: t("skills.pleaseInputName") }]}
          >
            <Input
              placeholder={t("skillPool.skillNamePlaceholder")}
              disabled={mode === "edit"}
            />
          </Form.Item>

          <Form.Item
            name="content"
            label="Content"
            rules={[{ required: true, validator: validateFrontmatter }]}
          >
            <MarkdownCopy
              content={drawerContent}
              showMarkdown={showMarkdown}
              onShowMarkdownChange={setShowMarkdown}
              editable={true}
              onContentChange={handleDrawerContentChange}
              textareaProps={{
                placeholder: t("skillPool.contentPlaceholder"),
                rows: 12,
              }}
            />
          </Form.Item>

          <Form.Item label={t("skills.config")}>
            <Input.TextArea
              rows={4}
              value={configText}
              onChange={(e) => {
                setConfigText(e.target.value);
              }}
              placeholder={t("skills.configPlaceholder")}
            />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}

export default SkillPoolPage;
