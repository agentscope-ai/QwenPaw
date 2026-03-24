import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Form,
  Modal,
  Select,
  Tooltip,
  message,
} from "@agentscope-ai/design";
import {
  DownloadOutlined,
  ImportOutlined,
  PlusOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";
import { SkillCard, SkillDrawer } from "./components";
import { useSkills } from "./useSkills";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import api from "../../../api";
import { parseErrorDetail } from "../../../utils/error";
import styles from "./index.module.less";

function SkillsPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const {
    skills,
    loading,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills,
  } = useSkills();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const [editingSkill, setEditingSkill] = useState<SkillSpec | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [form] = Form.useForm<SkillSpec>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | "download" | null>(
    null,
  );
  const [poolSkillNames, setPoolSkillNames] = useState<string[]>([]);
  const [workspaceSkillNames, setWorkspaceSkillNames] = useState<string[]>([]);
  const [rename, setRename] = useState("");

  const MAX_UPLOAD_SIZE_MB = 100;

  useEffect(() => {
    void api
      .listSkillPoolSkills()
      .then(setPoolSkills)
      .catch(() => undefined);
  }, [loading]);

  const workspaceSkillOptions = useMemo(
    () =>
      skills.map((skill) => ({
        label: skill.name,
        value: skill.name,
      })),
    [skills],
  );

  const poolSkillOptions = useMemo(
    () =>
      poolSkills.map((skill) => ({
        label: skill.name,
        value: skill.name,
      })),
    [poolSkills],
  );

  const closePoolModal = () => {
    setPoolModal(null);
    setPoolSkillNames([]);
    setWorkspaceSkillNames([]);
    setRename("");
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    e.target.value = "";

    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }

    const sizeMB = file.size / (1024 * 1024);
    if (sizeMB > MAX_UPLOAD_SIZE_MB) {
      message.warning(
        t("skills.fileSizeExceeded", { size: sizeMB.toFixed(1) }),
      );
      return;
    }

    await uploadSkill(file);
  };

  const handleCreate = () => {
    setEditingSkill(null);
    form.resetFields();
    form.setFieldsValue({
      enabled: false,
      channels: ["all"],
    });
    setDrawerOpen(true);
  };

  const supportedSkillUrlPrefixes = [
    "https://skills.sh/",
    "https://clawhub.ai/",
    "https://skillsmp.com/",
    "https://lobehub.com/",
    "https://market.lobehub.com/",
    "https://github.com/",
    "https://modelscope.cn/skills/",
  ];

  const isSupportedSkillUrl = (url: string) => {
    return supportedSkillUrlPrefixes.some((prefix) => url.startsWith(prefix));
  };

  const closeImportModal = () => {
    if (importing) {
      return;
    }
    setImportModalOpen(false);
    setImportUrl("");
    setImportUrlError("");
  };

  const handleImportFromHub = () => {
    setImportModalOpen(true);
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
    const success = await importFromHub(trimmed);
    if (success) {
      closeImportModal();
    }
  };

  const handleEdit = (skill: SkillSpec) => {
    setEditingSkill(skill);
    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      content: skill.content,
      enabled: skill.enabled,
      channels: skill.channels,
    });
    setDrawerOpen(true);
  };

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    await toggleEnabled(skill);
    await refreshSkills();
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    await deleteSkill(skill);
    await refreshSkills();
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingSkill(null);
  };

  const handleSubmit = async (values: SkillSpec) => {
    try {
      const wasEnabled = editingSkill?.enabled ?? false;
      const success = await createSkill(values.name, values.content);
      if (success) {
        await api.updateSkillChannels(values.name, values.channels || ["all"]);
        if (wasEnabled) {
          await toggleEnabled({ ...values, enabled: false } as SkillSpec);
        }
        setDrawerOpen(false);
        await refreshSkills();
      }
    } catch (error) {
      console.error("Submit failed", error);
    }
  };

  const handleUploadToPool = async () => {
    if (workspaceSkillNames.length === 0) return;
    try {
      for (const skillName of workspaceSkillNames) {
        await api.uploadWorkspaceSkillToPool({
          workspace_id: selectedAgent,
          skill_name: skillName,
          new_name:
            workspaceSkillNames.length === 1
              ? rename.trim() || undefined
              : undefined,
        });
      }
      message.success(t("skills.uploadedToPool"));
      closePoolModal();
      await refreshSkills();
      setPoolSkills(await api.listSkillPoolSkills());
    } catch (error) {
      const detail = parseErrorDetail(error);
      if (detail?.suggested_name) {
        setRename(detail.suggested_name);
        message.warning(t("skills.nameConflict"));
        return;
      }
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  const handleDownloadFromPool = async () => {
    if (poolSkillNames.length === 0) return;
    try {
      for (const skillName of poolSkillNames) {
        await api.downloadSkillPoolSkill({
          skill_name: skillName,
          targets: [
            {
              workspace_id: selectedAgent,
              target_name:
                poolSkillNames.length === 1
                  ? rename.trim() || undefined
                  : undefined,
            },
          ],
        });
      }
      message.success(t("skills.downloadedToWorkspace"));
      closePoolModal();
      await refreshSkills();
    } catch (error) {
      const detail = parseErrorDetail(error);
      const conflict = detail?.conflicts?.[0];
      if (conflict?.suggested_name) {
        setRename(conflict.suggested_name);
        message.warning(t("skills.nameConflict"));
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("common.download") + " failed",
      );
    }
  };

  return (
    <div className={styles.skillsPage}>
      <div className={styles.header}>
        <div className={styles.headerInfo}>
          <h1 className={styles.title}>{t("skills.title")}</h1>
          <p className={styles.description}>{t("skills.description")}</p>
        </div>
        <div className={styles.headerActions}>
          <input
            type="file"
            accept=".zip"
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: "none" }}
          />
          <div className={styles.headerActionsLeft}>
            <Tooltip title={t("skills.downloadFromPoolHint")}>
              <Button
                type="primary"
                className={styles.primaryTransferButton}
                onClick={() => setPoolModal("download")}
                icon={<DownloadOutlined />}
              >
                {t("common.download")}
              </Button>
            </Tooltip>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="primary"
                className={styles.primaryTransferButton}
                onClick={() => setPoolModal("upload")}
                icon={<SwapOutlined />}
              >
                {t("common.upload")}
              </Button>
            </Tooltip>
          </div>
          <div className={styles.headerActionsRight}>
            <Button
              type="default"
              className={styles.creationActionButton}
              onClick={handleUploadClick}
              icon={<UploadOutlined />}
              loading={uploading}
              disabled={uploading}
            >
              {t("skills.uploadSkill")}
            </Button>
            <Button
              type="default"
              className={styles.creationActionButton}
              onClick={handleImportFromHub}
              icon={<ImportOutlined />}
            >
              {t("skills.importSkills")}
            </Button>
            <Button
              type="default"
              className={styles.creationActionButton}
              onClick={handleCreate}
              icon={<PlusOutlined />}
            >
              {t("skills.createSkill")}
            </Button>
          </div>
        </div>
      </div>

      <Modal
        title={`${t("skills.importSkills")} Hub`}
        open={importModalOpen}
        onCancel={closeImportModal}
        maskClosable={!importing}
        closable={!importing}
        keyboard={!importing}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={importing ? cancelImport : closeImportModal}
              style={{ marginRight: 8 }}
            >
              {t(importing ? "skills.cancelImport" : "common.cancel")}
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
            External hub import is separate from the local Skill Pool.
          </p>
          <p className={styles.importHintTitle}>
            {t("skills.supportedSkillUrlSources")}
          </p>
          <ul className={styles.importHintList}>
            <li>https://skills.sh/</li>
            <li>https://clawhub.ai/</li>
            <li>https://skillsmp.com/</li>
            <li>https://lobehub.com/</li>
            <li>https://market.lobehub.com/</li>
            <li>https://github.com/</li>
            <li>https://modelscope.cn/skills/</li>
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

      {loading ? (
        <div className={styles.loading}>
          <span className={styles.loadingText}>{t("common.loading")}</span>
        </div>
      ) : skills.length === 0 ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyStateBadge}>
            {t("skills.emptyStateBadge")}
          </div>
          <h2 className={styles.emptyStateTitle}>
            {t("skills.emptyStateTitle")}
          </h2>
          <p className={styles.emptyStateText}>{t("skills.emptyStateText")}</p>
          <div className={styles.emptyStateActions}>
            <Button
              type="primary"
              className={styles.primaryTransferButton}
              onClick={() => setPoolModal("download")}
              icon={<DownloadOutlined />}
            >
              {t("skills.emptyStateDownload")}
            </Button>
            <Button
              type="default"
              className={styles.creationActionButton}
              onClick={handleCreate}
              icon={<PlusOutlined />}
            >
              {t("skills.emptyStateCreate")}
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {skills
            .slice()
            .sort((a, b) => {
              if (a.enabled && !b.enabled) return -1;
              if (!a.enabled && b.enabled) return 1;
              return a.name.localeCompare(b.name);
            })
            .map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                isHover={hoverKey === skill.name}
                onClick={() => handleEdit(skill)}
                onMouseEnter={() => setHoverKey(skill.name)}
                onMouseLeave={() => setHoverKey(null)}
                onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
                onDelete={(e) => handleDelete(skill, e)}
              />
            ))}
        </div>
      )}

      <Modal
        open={poolModal !== null}
        onCancel={closePoolModal}
        onOk={
          poolModal === "upload" ? handleUploadToPool : handleDownloadFromPool
        }
        title={
          poolModal === "upload"
            ? t("skills.uploadToPool")
            : t("skills.downloadFromPool")
        }
      >
        <div style={{ display: "grid", gap: 12 }}>
          {poolModal === "upload" ? (
            <>
              <div className={styles.bulkActions}>
                <Button
                  size="small"
                  onClick={() =>
                    setWorkspaceSkillNames(
                      workspaceSkillOptions.map((item) => item.value),
                    )
                  }
                >
                  {t("skills.selectAll")}
                </Button>
                <Button size="small" onClick={() => setWorkspaceSkillNames([])}>
                  {t("skills.clearSelection")}
                </Button>
              </div>
              <Select
                mode="multiple"
                placeholder={t("skills.selectWorkspaceSkill")}
                value={workspaceSkillNames}
                options={workspaceSkillOptions}
                onChange={(value: string[]) => setWorkspaceSkillNames(value)}
              />
            </>
          ) : (
            <>
              <div className={styles.bulkActions}>
                <Button
                  size="small"
                  onClick={() =>
                    setPoolSkillNames(
                      poolSkillOptions.map((item) => item.value),
                    )
                  }
                >
                  {t("skills.selectAll")}
                </Button>
                <Button size="small" onClick={() => setPoolSkillNames([])}>
                  {t("skills.clearSelection")}
                </Button>
              </div>
              <Select
                mode="multiple"
                placeholder={t("skills.selectPoolItem")}
                value={poolSkillNames}
                options={poolSkillOptions}
                onChange={(value: string[]) => setPoolSkillNames(value)}
              />
            </>
          )}
          <Form layout="vertical">
            <Form.Item
              label={t("skills.renameOptional")}
              extra={
                poolModal === "upload"
                  ? workspaceSkillNames.length > 1
                    ? t("skills.renameSingleOnly")
                    : undefined
                  : poolSkillNames.length > 1
                  ? t("skills.renameSingleOnly")
                  : undefined
              }
            >
              <input
                className={styles.importUrlInput}
                value={rename}
                onChange={(e) => setRename(e.target.value)}
                placeholder={t("skills.renamePlaceholder")}
                disabled={
                  poolModal === "upload"
                    ? workspaceSkillNames.length !== 1
                    : poolSkillNames.length !== 1
                }
              />
            </Form.Item>
          </Form>
        </div>
      </Modal>

      <SkillDrawer
        open={drawerOpen}
        editingSkill={editingSkill}
        form={form}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default SkillsPage;
