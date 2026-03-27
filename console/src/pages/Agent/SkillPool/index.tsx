import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  DeleteOutlined,
  ImportOutlined,
  PlusOutlined,
  SendOutlined,
  SyncOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import type {
  BuiltinImportSpec,
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../api/types";
import { parseErrorDetail } from "../../../utils/error";
import {
  getSkillDisplaySource,
  getPoolBuiltinStatusLabel,
  getSkillVisual,
  parseFrontmatter,
  isSupportedSkillUrl,
  SUPPORTED_SKILL_URL_PREFIXES,
  useConflictRenameModal,
} from "../Skills/components";
import { MarkdownCopy } from "../../../components/MarkdownCopy/MarkdownCopy";
import styles from "../Skills/index.module.less";

type PoolMode = "broadcast" | "create" | "edit";

function SkillPoolPage() {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<PoolSkillSpec[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<PoolMode | null>(null);
  const [activeSkill, setActiveSkill] = useState<PoolSkillSpec | null>(null);
  const [broadcastSkillNames, setBroadcastSkillNames] = useState<string[]>([]);
  const [targetWorkspaceIds, setTargetWorkspaceIds] = useState<string[]>([]);
  const [configText, setConfigText] = useState("{}");
  const zipInputRef = useRef<HTMLInputElement>(null);
  const [importBuiltinModalOpen, setImportBuiltinModalOpen] = useState(false);
  const [builtinSources, setBuiltinSources] = useState<BuiltinImportSpec[]>([]);
  const [selectedBuiltinNames, setSelectedBuiltinNames] = useState<string[]>([]);
  const [importBuiltinLoading, setImportBuiltinLoading] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const [importing, setImporting] = useState(false);
  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // Form state for create/edit drawer
  const [form] = Form.useForm();
  const [drawerContent, setDrawerContent] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(true);

  const builtinSkillNames = useMemo(
    () =>
      skills
        .filter((skill) => skill.source === "builtin")
        .map((skill) => skill.name),
    [skills],
  );

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
    setBroadcastSkillNames([]);
    setTargetWorkspaceIds([]);
    setConfigText("{}");
  };

  const openCreate = () => {
    setMode("create");
    setDrawerContent("");
    setConfigText("{}");
    form.resetFields();
    form.setFieldsValue({
      name: "",
      content: "",
    });
  };

  const openBroadcast = (skill?: PoolSkillSpec) => {
    setMode("broadcast");
    setBroadcastSkillNames(skill ? [skill.name] : []);
    setTargetWorkspaceIds([]);
  };

  const openImportBuiltin = async () => {
    try {
      setImportBuiltinLoading(true);
      const sources = await api.listPoolBuiltinSources();
      setBuiltinSources(sources);
      setSelectedBuiltinNames([]);
      setImportBuiltinModalOpen(true);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.importBuiltinFailed"),
      );
    } finally {
      setImportBuiltinLoading(false);
    }
  };

  const closeImportBuiltin = () => {
    if (importBuiltinLoading) return;
    setImportBuiltinModalOpen(false);
    setSelectedBuiltinNames([]);
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

  const handleBroadcast = async () => {
    if (broadcastSkillNames.length === 0 || targetWorkspaceIds.length === 0) {
      return;
    }
    try {
      for (const skillName of broadcastSkillNames) {
        let renameMap: Record<string, string> = {};

        while (true) {
          try {
            await api.downloadSkillPoolSkill({
              skill_name: skillName,
              targets: targetWorkspaceIds.map((workspace_id) => ({
                workspace_id,
                target_name: renameMap[workspace_id] || undefined,
              })),
            });
            break;
          } catch (error) {
            const detail = parseErrorDetail(error);
            const conflicts = Array.isArray(detail?.conflicts)
              ? detail.conflicts
              : [];
            if (!conflicts.length) {
              throw error;
            }

            const renameItems = conflicts
              .map(
                (c: {
                  workspace_id?: string;
                  suggested_name?: string;
                }) => {
                  if (!c.workspace_id || !c.suggested_name) {
                    return null;
                  }
                  const workspaceLabel =
                    workspaces.find((w) => w.agent_id === c.workspace_id)
                      ?.agent_name ||
                    c.workspace_id;
                  return {
                    key: c.workspace_id,
                    label: workspaceLabel,
                    suggested_name: c.suggested_name,
                  };
                },
              )
              .filter(
                (
                  item,
                ): item is {
                  key: string;
                  label: string;
                  suggested_name: string;
                } => item !== null,
              );

            if (!renameItems.length) {
              throw error;
            }

            const nextRenameMap = await showConflictRenameModal(
              renameItems.map((item) => ({
                ...item,
                suggested_name:
                  renameMap[item.key] || item.suggested_name,
              })),
            );
            if (!nextRenameMap) {
              return;
            }
            renameMap = {
              ...renameMap,
              ...nextRenameMap,
            };
          }
        }
      }
      message.success(t("skillPool.broadcastSuccess"));
      closeModal();
      await loadData();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.broadcastFailed"),
      );
    }
  };

  const handleImportBuiltins = async (overwriteConflicts: boolean = false) => {
    if (selectedBuiltinNames.length === 0) return;
    try {
      setImportBuiltinLoading(true);
      const result = await api.importSelectedPoolBuiltins({
        skill_names: selectedBuiltinNames,
        overwrite_conflicts: overwriteConflicts,
      });
      const imported = Array.isArray(result.imported) ? result.imported : [];
      const updated = Array.isArray(result.updated) ? result.updated : [];
      const unchanged = Array.isArray(result.unchanged)
        ? result.unchanged
        : [];

      if (!imported.length && !updated.length && unchanged.length) {
        message.info(t("skillPool.importBuiltinNoChanges"));
        closeImportBuiltin();
        return;
      }

      if (imported.length || updated.length) {
        message.success(
          t("skillPool.importBuiltinSuccess", {
            names: [...imported, ...updated].join(", "),
          }),
        );
      }
      closeImportBuiltin();
      await loadData();
    } catch (error) {
      const detail = parseErrorDetail(error);
      const conflicts = Array.isArray(detail?.conflicts) ? detail.conflicts : [];
      if (conflicts.length && !overwriteConflicts) {
        Modal.confirm({
          title: t("skillPool.importBuiltinConflictTitle"),
          content: (
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skillPool.importBuiltinConflictContent")}</div>
              {conflicts.map((item) => (
                <div key={item.skill_name}>
                  <strong>{item.skill_name}</strong>
                  {"  "}
                  {t("skillPool.currentVersion")}:{" "}
                  {item.current_version_text || "-"}
                  {"  ->  "}
                  {t("skillPool.sourceVersion")}:{" "}
                  {item.source_version_text || "-"}
                </div>
              ))}
            </div>
          ),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: async () => {
            await handleImportBuiltins(true);
          },
        });
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("skillPool.importBuiltinFailed"),
      );
    } finally {
      setImportBuiltinLoading(false);
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

    const skillName = (values.name || "").trim();
    const skillContent = drawerContent || values.content;

    if (!skillName || !skillContent.trim()) return;

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
      if (result.mode === "noop") {
        closeDrawer();
        return;
      }
      const savedAsNew =
        mode === "edit" && activeSkill && result.name !== activeSkill.name;
      message.success(
        savedAsNew
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
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: detail.suggested_name,
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            form.setFieldsValue({ name: newName });
            await handleSavePoolSkill();
          }
        }
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
        ? t("skillPool.deleteBuiltinConfirm")
        : t("skillPool.deleteConfirm"),
      okText: t("common.delete"),
      okType: "danger",
      onOk: async () => {
        await api.deleteSkillPoolSkill(skill.name);
        message.success(t("skillPool.deletedFromPool"));
        await loadData();
      },
    });
  };

  const handleZipImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    let renameMap: Record<string, string> | undefined;
    while (true) {
      try {
        const result = await api.uploadSkillPoolZip(file, {
          overwrite: false,
          rename_map: renameMap,
        });
        if (result.count > 0) {
          message.success(
            t("skillPool.imported", { names: result.imported.join(", ") }),
          );
        } else {
          message.info(t("skillPool.noNewImports"));
        }
        await loadData();
        break;
      } catch (error) {
        const detail = parseErrorDetail(error);
        const conflicts = Array.isArray(detail?.conflicts)
          ? detail.conflicts
          : [];
        if (conflicts.length === 0) {
          message.error(
            error instanceof Error
              ? error.message
              : t("skillPool.zipImportFailed"),
          );
          break;
        }
        const newRenames = await showConflictRenameModal(
          conflicts.map((c: { skill_name?: string; suggested_name?: string }) => ({
            key: c.skill_name || "",
            label: c.skill_name || "",
            suggested_name: c.suggested_name || "",
          })),
        );
        if (!newRenames) break;
        renameMap = { ...renameMap, ...newRenames };
      }
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

  const handleConfirmImport = async (targetName?: string) => {
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
        target_name: targetName,
      });
      message.success(`${t("common.create")}: ${result.name}`);
      closeImportModal();
      await loadData();
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        const skillName = detail?.skill_name || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(detail.suggested_name),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) {
            await handleConfirmImport(newName);
          }
        }
        return;
      }
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
          <Tooltip title={t("skillPool.broadcastHint")}>
            <Button
              type="primary"
              className={styles.primaryTransferButton}
              icon={<SendOutlined />}
              onClick={() => openBroadcast()}
            >
              {t("skillPool.broadcast")}
            </Button>
          </Tooltip>
          <Tooltip title={t("skillPool.importBuiltinHint")}>
            <Button
              type="default"
              icon={<SyncOutlined />}
              onClick={() => void openImportBuiltin()}
            >
              {t("skillPool.importBuiltin")}
            </Button>
          </Tooltip>
          <Tooltip title={t("skills.importHubHint")}>
            <Button
              type="default"
              icon={<ImportOutlined />}
              onClick={() => setImportModalOpen(true)}
            >
              {t("skills.importHub")}
            </Button>
          </Tooltip>
          <Tooltip title={t("skills.uploadZipHint")}>
            <Button
              type="default"
              icon={<UploadOutlined />}
              onClick={() => zipInputRef.current?.click()}
            >
              {t("skills.uploadZip")}
            </Button>
          </Tooltip>
          <Tooltip title={t("skills.createSkillHint")}>
            <Button type="default" icon={<PlusOutlined />} onClick={openCreate}>
              {t("skills.createSkill")}
            </Button>
          </Tooltip>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {skills.map((skill) => (
            <Card
              key={skill.name}
              className={styles.skillCard}
              onClick={() => openEdit(skill)}
              style={{ cursor: "pointer" }}
            >
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
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    <span
                      className={
                        getSkillDisplaySource(skill.source) ===
                        "builtin"
                          ? styles.builtinTag
                          : styles.customizedTag
                      }
                    >
                      {getSkillDisplaySource(skill.source)}
                    </span>
                  </div>
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
                <div className={styles.descriptionSection}>
                  <div className={styles.infoLabel}>
                    {t("skillPool.status")}
                  </div>
                  <div className={styles.infoBlock}>
                    {getPoolBuiltinStatusLabel(skill.sync_status, t)}
                  </div>
                </div>
              </div>
              <div className={styles.cardFooter}>
                <Button
                  type="link"
                  size="small"
                  className={styles.accentLinkAction}
                  icon={<SendOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    openBroadcast(skill);
                  }}
                >
                  {t("skillPool.broadcast")}
                </Button>
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDelete(skill);
                  }}
                >
                  {t("skillPool.delete")}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        title={t("skills.importHub")}
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
              onClick={() => handleConfirmImport()}
              loading={importing}
              disabled={importing || !importUrl.trim() || !!importUrlError}
            >
              {t("skills.importHub")}
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
        open={mode === "broadcast"}
        onCancel={closeModal}
        onOk={handleBroadcast}
        okButtonProps={{
          disabled:
            broadcastSkillNames.length === 0 || targetWorkspaceIds.length === 0,
        }}
        title={t("skillPool.broadcast")}
        width={640}
      >
        <div style={{ display: "grid", gap: 12 }}>
          <div className={styles.pickerLabel}>{t("skills.selectPoolItem")}</div>
          <div className={styles.bulkActions}>
            <Button
              size="small"
              onClick={() =>
                setBroadcastSkillNames(skills.map((skill) => skill.name))
              }
            >
              {t("agent.selectAll")}
            </Button>
            <Button
              size="small"
              onClick={() => setBroadcastSkillNames(builtinSkillNames)}
            >
              {t("agent.selectBuiltin")}
            </Button>
            <Button size="small" onClick={() => setBroadcastSkillNames([])}>
              {t("skills.clearSelection")}
            </Button>
          </div>
          <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
            {skills.map((skill) => {
              const selected = broadcastSkillNames.includes(skill.name);
              return (
                <div
                  key={skill.name}
                  className={`${styles.pickerCard} ${styles.compactPickerCard} ${
                    selected ? styles.pickerCardSelected : ""
                  }`}
                  onClick={() =>
                    setBroadcastSkillNames(
                      selected
                        ? broadcastSkillNames.filter((name) => name !== skill.name)
                        : [...broadcastSkillNames, skill.name],
                    )
                  }
                >
                  {selected && (
                    <span
                      className={`${styles.pickerCheck} ${styles.compactPickerCheck}`}
                    >
                      <CheckOutlined />
                    </span>
                  )}
                  <div
                    className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                  >
                    {skill.name}
                  </div>
                </div>
              );
            })}
          </div>

          <div className={styles.pickerLabel}>
            {t("skillPool.selectWorkspaces")}
          </div>
          <div className={styles.bulkActions}>
            <Button
              size="small"
              onClick={() => setTargetWorkspaceIds(workspaces.map((ws) => ws.agent_id))}
            >
              {t("skillPool.allWorkspaces")}
            </Button>
            <Button size="small" onClick={() => setTargetWorkspaceIds([])}>
              {t("skills.clearSelection")}
            </Button>
          </div>
          <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
            {workspaces.map((workspace) => {
              const selected = targetWorkspaceIds.includes(workspace.agent_id);
              return (
                <div
                  key={workspace.agent_id}
                  className={`${styles.pickerCard} ${styles.compactPickerCard} ${
                    selected ? styles.pickerCardSelected : ""
                  }`}
                  onClick={() =>
                    setTargetWorkspaceIds(
                      selected
                        ? targetWorkspaceIds.filter(
                            (id) => id !== workspace.agent_id,
                          )
                        : [...targetWorkspaceIds, workspace.agent_id],
                    )
                  }
                >
                  {selected && (
                    <span
                      className={`${styles.pickerCheck} ${styles.compactPickerCheck}`}
                    >
                      <CheckOutlined />
                    </span>
                  )}
                  <div
                    className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                  >
                    {workspace.agent_name || workspace.agent_id}
                  </div>
                </div>
              );
            })}
          </div>

        </div>
      </Modal>

      <Modal
        open={importBuiltinModalOpen}
        onCancel={closeImportBuiltin}
        onOk={() => void handleImportBuiltins()}
        title={t("skillPool.importBuiltin")}
        okButtonProps={{
          disabled: selectedBuiltinNames.length === 0,
          loading: importBuiltinLoading,
        }}
        width={720}
      >
        <div style={{ display: "grid", gap: 12 }}>
          <div className={styles.pickerLabel}>{t("skillPool.importBuiltinHint")}</div>
          <div className={styles.bulkActions}>
            <Button
              size="small"
              onClick={() =>
                setSelectedBuiltinNames(builtinSources.map((item) => item.name))
              }
            >
              {t("agent.selectAll")}
            </Button>
            <Button size="small" onClick={() => setSelectedBuiltinNames([])}>
              {t("skills.clearSelection")}
            </Button>
          </div>
          <div className={styles.pickerGrid}>
            {builtinSources.map((item) => {
              const selected = selectedBuiltinNames.includes(item.name);
              return (
                <div
                  key={item.name}
                  className={`${styles.pickerCard} ${
                    selected ? styles.pickerCardSelected : ""
                  }`}
                  onClick={() =>
                    setSelectedBuiltinNames(
                      selected
                        ? selectedBuiltinNames.filter((name) => name !== item.name)
                        : [...selectedBuiltinNames, item.name],
                    )
                  }
                >
                  {selected && (
                    <span className={styles.pickerCheck}>
                      <CheckOutlined />
                    </span>
                  )}
                  <div className={styles.pickerCardTitle}>{item.name}</div>
                  <div className={styles.pickerCardMeta}>
                    {t("skillPool.sourceVersion")}: {item.version_text || "-"}
                  </div>
                  <div className={styles.pickerCardMeta}>
                    {t("skillPool.currentVersion")}:{" "}
                    {item.current_version_text || "-"}
                  </div>
                  <div className={styles.pickerCardMeta}>
                    {t(`skillPool.importStatus${item.status === "current"
                      ? "Current"
                      : item.status === "conflict"
                      ? "Conflict"
                      : "Missing"}`)}
                  </div>
                </div>
              );
            })}
          </div>
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
        {mode === "edit" && activeSkill && (
          <div className={styles.metaStack} style={{ marginBottom: 16 }}>
            <div className={styles.infoSection}>
              <div className={styles.infoLabel}>
                {t("skillPool.status")}
              </div>
              <div className={styles.infoBlock}>
                {getPoolBuiltinStatusLabel(activeSkill.sync_status, t)}
              </div>
            </div>
          </div>
        )}
        <Form form={form} layout="vertical" onFinish={handleSavePoolSkill}>
          <Form.Item
            name="name"
            label={t("skillPool.skillName")}
            rules={[{ required: true, message: t("skills.pleaseInputName") }]}
          >
            <Input
              placeholder={t("skillPool.skillNamePlaceholder")}
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

      {conflictRenameModal}
    </div>
  );
}

export default SkillPoolPage;
