import { useState, useRef, useEffect, useCallback } from "react";
import { Button, Modal, message } from "@agentscope-ai/design";
import {
  DownloadOutlined,
  PlusOutlined,
  UploadOutlined,
  SearchOutlined,
  FilterOutlined,
  CheckOutlined,
} from "@ant-design/icons";
import { Input, Spin, Dropdown, MenuProps, Upload, Form } from "antd";
import type { SkillSpec } from "../../../api/types";
import { defaultSkillApi } from "../../../api/modules/defaultSkills";
import { SkillCard } from "./components/SkillCard";
import { SkillDrawer } from "../../Agent/Skills/components/SkillDrawer";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

export default function DefaultSkills() {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importUrlError, setImportUrlError] = useState("");
  const importTaskIdRef = useRef<string | null>(null);
  const importCancelReasonRef = useRef<"manual" | "timeout" | null>(null);
  const [filterEnabled, setFilterEnabled] = useState<string | null>(null);
  const [filterBuiltin, setFilterBuiltin] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form] = Form.useForm<SkillSpec>();

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
    console.log("handleImportFromHub 被调用！打开导入模态框！");
    setImportModalOpen(true);
  };

  const handleImportUrlChange = (value: string) => {
    setImportUrl(value);
    const trimmed = value.trim();
    if (trimmed && !isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource", "不支持的技能 URL 源"));
      return;
    }
    setImportUrlError("");
  };

  const cancelImport = useCallback(() => {
    if (!importing) return;
    importCancelReasonRef.current = "manual";
    const taskId = importTaskIdRef.current;
    if (!taskId) return;
    void defaultSkillApi.cancelHubSkillInstall(taskId);
  }, [importing]);

  const importFromHub = async (input: string) => {
    const text = (input || "").trim();
    if (!text) {
      message.warning(t("skills.pleaseProvideUrl", "请提供技能 URL"));
      return false;
    }
    if (!text.startsWith("http://") && !text.startsWith("https://")) {
      message.warning(
        t("skills.invalidUrlProtocol", "请输入以 http:// 或 https:// 开头的有效 URL"),
      );
      return false;
    }
    const timeoutMs = 90_000;
    const pollMs = 1_000;
    const startedAt = Date.now();
    try {
      setImporting(true);
      importCancelReasonRef.current = null;
      const payload = { bundle_url: text, overwrite: false };
      
      console.log("Calling startHubSkillInstall with payload:", payload);
      const task = await defaultSkillApi.startHubSkillInstall(payload);
      console.log("Received task:", task);
      importTaskIdRef.current = task.task_id;

      while (importTaskIdRef.current) {
        console.log("Polling status for task:", importTaskIdRef.current);
        const status = await defaultSkillApi.getHubSkillInstallStatus(task.task_id);
        console.log("Received status:", status);

        if (status.status === "completed" && status.result?.installed) {
          message.success(`Imported skill: ${status.result.name}`);
          await loadSkills();
          return true;
        }

        if (status.status === "failed") {
          throw new Error(status.error || "Import failed");
        }

        if (status.status === "cancelled") {
          message.warning(
            t(
              importCancelReasonRef.current === "timeout"
                ? "skills.importTimeout"
                : "skills.importCancelled",
            ),
          );
          return false;
        }

        if (Date.now() - startedAt >= timeoutMs) {
          importCancelReasonRef.current = "timeout";
          await defaultSkillApi.cancelHubSkillInstall(task.task_id);
        }

        await new Promise((resolve) => window.setTimeout(resolve, pollMs));
      }

      return false;
    } catch (error) {
      console.error("Import failed", error);
      if (error instanceof Error) {
        message.error(`Import failed: ${error.message}`);
      } else {
        message.error("Import failed");
      }
      return false;
    } finally {
      importTaskIdRef.current = null;
      importCancelReasonRef.current = null;
      setImporting(false);
    }
  };

  const handleConfirmImport = async () => {
    if (importing) return;
    const trimmed = importUrl.trim();
    if (!trimmed) return;
    if (!isSupportedSkillUrl(trimmed)) {
      setImportUrlError(t("skills.invalidSkillUrlSource", "不支持的技能 URL 源"));
      return;
    }
    const success = await importFromHub(trimmed);
    if (success) {
      closeImportModal();
    }
  };

  const loadSkills = useCallback(async () => {
    try {
      setLoading(true);
      const data = await defaultSkillApi.listDefaultSkills();
      setSkills(data);
    } catch (err) {
      console.error("Failed to load default skills:", err);
      message.error(t("defaultSkills.loadFailed", "加载内置技能失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  const filteredSkills = skills.filter((skill) => {
    const matchesSearch = skill.name.toLowerCase().includes(searchText.toLowerCase()) ||
      (skill.description || "").toLowerCase().includes(searchText.toLowerCase());
    
    const matchesEnabled = filterEnabled === null || 
      (filterEnabled === "enabled" && skill.enabled) || 
      (filterEnabled === "disabled" && !skill.enabled);
    
    const matchesBuiltin = filterBuiltin === null || 
      (filterBuiltin === "builtin" && skill.source === "builtin") || 
      (filterBuiltin === "inactive" && skill.source === "inactive");
    
    return matchesSearch && matchesEnabled && matchesBuiltin;
  });

  const handleToggleEnabled = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (skill.enabled) {
        await defaultSkillApi.disableSkillInAgent(skill.name);
        message.success(t("defaultSkills.disabledSuccess", "已禁用技能"));
      } else {
        await defaultSkillApi.enableSkillInAgent(skill.name);
        message.success(t("defaultSkills.enabledSuccess", "已启用技能"));
      }
      await loadSkills();
    } catch (err) {
      console.error("Failed to toggle skill:", err);
      message.error(t("defaultSkills.toggleFailed", "操作失败"));
    }
  };

  const handleMoveToInactive = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await defaultSkillApi.moveToInactive(skill.name);
      message.success(t("defaultSkills.movedToInactive", "已移动到非内置"));
      await loadSkills();
    } catch (err) {
      console.error("Failed to move skill:", err);
      message.error(t("defaultSkills.moveFailed", "移动失败"));
    }
  };

  const handleMoveToBuiltin = async (skill: SkillSpec, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await defaultSkillApi.moveToBuiltin(skill.name);
      message.success(t("defaultSkills.movedToBuiltin", "已移动到内置"));
      await loadSkills();
    } catch (err) {
      console.error("Failed to move skill:", err);
      message.error(t("defaultSkills.moveFailed", "移动失败"));
    }
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    Modal.confirm({
      title: t("defaultSkills.deleteConfirmTitle", "确认删除"),
      content: t("defaultSkills.deleteConfirmContent", "确定要删除这个技能吗？此操作不可撤销。"),
      okText: t("common.delete"),
      okType: "danger",
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          await defaultSkillApi.deleteInactiveSkill(skill.name);
          message.success(t("defaultSkills.deletedSuccess", "已删除技能"));
          await loadSkills();
        } catch (err) {
          console.error("Failed to delete skill:", err);
          message.error(t("defaultSkills.deleteFailed", "删除失败"));
        }
      },
    });
  };

  const handleUpload = async (file: File) => {
    try {
      setUploading(true);
      const result = await defaultSkillApi.uploadDefaultSkill(file, { overwrite: true });
      if (result.count > 0) {
        message.success(
          t("defaultSkills.uploadSuccess", "成功导入 {{count}} 个技能", { count: result.count })
        );
        await loadSkills();
      } else {
        message.warning(t("defaultSkills.noSkillsImported", "没有导入任何技能"));
      }
    } catch (err) {
      console.error("Failed to upload skills:", err);
      message.error(t("defaultSkills.uploadFailed", "上传失败"));
    } finally {
      setUploading(false);
    }
    return false;
  };

  const handleCreate = () => {
    form.resetFields();
    setDrawerOpen(true);
  };

  const handleCreateSubmit = async (values: SkillSpec) => {
    try {
      const result = await defaultSkillApi.createDefaultSkill(values);
      if (result.created) {
        message.success(t("defaultSkills.createdSuccess", "技能创建成功"));
        setDrawerOpen(false);
        await loadSkills();
      } else {
        message.error(t("defaultSkills.createFailed", "技能创建失败"));
      }
    } catch (err) {
      console.error("Failed to create skill:", err);
      message.error(t("defaultSkills.createFailed", "技能创建失败"));
    }
  };

  const filterItems: MenuProps["items"] = [
    {
      type: "group",
      label: "启用状态",
      children: [
        {
          key: "enabled-all",
          label: "全部",
          icon: filterEnabled === null ? <CheckOutlined /> : null,
          onClick: () => setFilterEnabled(null),
        },
        {
          key: "enabled-true",
          label: "已启用",
          icon: filterEnabled === "enabled" ? <CheckOutlined /> : null,
          onClick: () => setFilterEnabled("enabled"),
        },
        {
          key: "enabled-false",
          label: "未启用",
          icon: filterEnabled === "disabled" ? <CheckOutlined /> : null,
          onClick: () => setFilterEnabled("disabled"),
        },
      ],
    },
    {
      type: "divider",
    },
    {
      type: "group",
      label: "内置状态",
      children: [
        {
          key: "builtin-all",
          label: "全部",
          icon: filterBuiltin === null ? <CheckOutlined /> : null,
          onClick: () => setFilterBuiltin(null),
        },
        {
          key: "builtin-true",
          label: "内置",
          icon: filterBuiltin === "builtin" ? <CheckOutlined /> : null,
          onClick: () => setFilterBuiltin("builtin"),
        },
        {
          key: "builtin-false",
          label: "非内置",
          icon: filterBuiltin === "inactive" ? <CheckOutlined /> : null,
          onClick: () => setFilterBuiltin("inactive"),
        },
      ],
    },
  ];

  if (loading) {
    return (
      <div className={styles.container}>
        <div style={{ textAlign: "center", padding: "60px" }}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.title}>
            {t("defaultSkills.title", "内置技能")}
          </h1>
          <p className={styles.description}>
            {t("defaultSkills.description", "管理 CoPaw 的内置和非内置技能")}
          </p>
        </div>
        <div className={styles.headerRight}>
          <Input
            placeholder={t("defaultSkills.searchPlaceholder", "搜索技能...")}
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className={styles.searchInput}
            allowClear
            style={{ width: 200 }}
          />
          <Dropdown menu={{ items: filterItems }} placement="bottomRight">
            <Button icon={<FilterOutlined />} />
          </Dropdown>
          <Upload
            beforeUpload={handleUpload}
            showUploadList={false}
            accept=".zip"
          >
            <Button
              type="primary"
              icon={<UploadOutlined />}
              loading={uploading}
            >
              {t("defaultSkills.upload", "上传技能")}
            </Button>
          </Upload>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleImportFromHub}
          >
            {t("defaultSkills.importFromHub", "导入技能")}
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
          >
            {t("defaultSkills.create", "创建")}
          </Button>
        </div>
      </div>

      <Modal
        title={t("skills.importFromHub", "从技能市场导入")}
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
              {t("defaultSkills.importFromHub", "导入技能")}
            </Button>
          </div>
        }
        width={760}
      >
        <div className={styles.importHintBlock}>
          <p className={styles.importHintTitle}>
            {t("skills.supportedSkillUrlSources", "当前支持的技能 URL 来源：")}
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

          <p className={styles.importHintTitle} style={{ marginTop: '20px' }}>
            {t("skills.urlExamples", "URL 示例：")}
          </p>
          <ul className={styles.importHintList}>
            <li>https://skills.sh/vercel-labs/skills/find-skills</li>
            <li>https://lobehub.com/zh/skills/openclaw-skills-cli-developer</li>
            <li>https://market.lobehub.com/api/v1/skills/openclaw-skills-cli-developer/download</li>
            <li>https://github.com/anthropics/skills/tree/main/skills/skill-creator</li>
            <li>https://modelscope.cn/skills/@anthropics/skill-creator</li>
          </ul>
        </div>

        <input
          className={styles.importUrlInput}
          value={importUrl}
          onChange={(e) => handleImportUrlChange(e.target.value)}
          placeholder={t("skills.enterSkillUrl", "在此粘贴技能 URL")}
          disabled={importing}
        />
        {importUrlError ? (
          <div className={styles.importUrlError}>{importUrlError}</div>
        ) : null}
        {importing ? (
          <div className={styles.importLoadingText}>{t("common.loading", "正在加载...")}</div>
        ) : null}
      </Modal>

      <SkillDrawer
        open={drawerOpen}
        editingSkill={null}
        form={form}
        onClose={() => setDrawerOpen(false)}
        onSubmit={handleCreateSubmit}
      />

      {filteredSkills.length === 0 ? (
        <div className={styles.emptyState}>
          <p>{searchText ? t("defaultSkills.noResults", "没有找到匹配的技能") : t("defaultSkills.noSkills", "暂无技能")}</p>
        </div>
      ) : (
        <div className={styles.skillsGrid}>
          {filteredSkills.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              onToggleEnabled={(e) => handleToggleEnabled(skill, e)}
              onMoveToInactive={(e) => handleMoveToInactive(skill, e)}
              onMoveToBuiltin={(e) => handleMoveToBuiltin(skill, e)}
              onDelete={(e) => handleDelete(skill, e)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
