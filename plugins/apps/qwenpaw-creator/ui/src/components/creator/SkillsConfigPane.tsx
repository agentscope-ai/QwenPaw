import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { Button, Dropdown, Input, Modal, Switch, Tooltip, message } from "antd";
import { Eye, Globe, Pencil, Plus, Trash2, Upload } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteSkill,
  getSkillContent,
  importSkillFromUrl,
  listSkills,
  saveSkill,
  setSkillEnabled,
  uploadSkillZip,
  type SkillItem,
} from "@/api/creator";

const SKILL_TEMPLATE = `---
name: my-video-skill
description: |
  一句话说明适用场景与产出，例如“美食短视频的开场钩子与镜头节奏模板”。
---

# 技能标题

## 适用场景
Agent 在什么情况下应参考本技能（例如：编排某类短视频分镜时）。

## 知识要点
- 开场 3 秒如何留住观众。
- 镜头节奏、转场与单镜时长控制。
- 文案/字幕的语气与版式规范。

## 产出规范
遵循本技能后，Agent 应产出什么样的结果。
`;

/** First sentence of a skill description, for a compact list preview. */
function briefDescription(description: string | null): string {
  const text = (description || "").replace(/\s+/g, " ").trim();
  return text.split("。")[0];
}

/** Drop the leading YAML front matter so only the body gets rendered. */
function stripFrontmatter(text: string): string {
  const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/.exec(text);
  return match ? text.slice(match[0].length) : text;
}

/** Skill names are filesystem identifiers — a lowercase slug (matches backend). */
const SKILL_NAME_RE = /^[a-z0-9][a-z0-9._-]*$/;

/** The backend refuses anything else, and a market page URL is never a bare host. */
const SKILL_URL_RE = /^https?:\/\//;

export default function SkillsConfigPane() {
  const { t } = useTranslation();
  const [items, setItems] = useState<SkillItem[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingName, setEditingName] = useState("");
  const [name, setName] = useState("");
  const [content, setContent] = useState(SKILL_TEMPLATE);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [urlOpen, setUrlOpen] = useState(false);
  const [urlValue, setUrlValue] = useState("");
  const [urlTarget, setUrlTarget] = useState("");
  const [importingUrl, setImportingUrl] = useState(false);
  const [previewMode, setPreviewMode] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Monotonic guard so a slow openEdit/openPreview read cannot land after a
  // newer open (or a create) and clobber the modal with stale content.
  const editSeqRef = useRef(0);
  // Same guard for the URL import: it owns closing and clearing that modal,
  // so a late completion cannot touch a session the user already restarted.
  const importSeqRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const res = await listSkills();
      setItems(res.items);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.loadFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const openCreate = () => {
    editSeqRef.current += 1;
    setPreviewMode(false);
    setShowPreview(false);
    setEditingName("");
    setName("");
    setContent(SKILL_TEMPLATE);
    setTruncated(false);
    setSaving(false);
    setEditorOpen(true);
  };

  const openEdit = async (item: SkillItem) => {
    editSeqRef.current += 1;
    const seq = editSeqRef.current;
    try {
      const res = await getSkillContent(item.name);
      if (seq !== editSeqRef.current) return;
      setPreviewMode(false);
      setShowPreview(false);
      setEditingName(item.name);
      setName(item.name);
      setContent(res.content);
      setTruncated(res.truncated);
      setSaving(false);
      setEditorOpen(true);
    } catch {
      // Never fall back to a saveable template: it would overwrite the real
      // skill on save. Surface the failure and leave the modal untouched.
      if (seq !== editSeqRef.current) return;
      message.error(t("skills.readFailed"));
    }
  };

  const openPreview = async (item: SkillItem) => {
    editSeqRef.current += 1;
    const seq = editSeqRef.current;
    try {
      const res = await getSkillContent(item.name);
      if (seq !== editSeqRef.current) return;
      setPreviewMode(true);
      setShowPreview(true);
      setEditingName(item.name);
      setName(item.name);
      setContent(res.content);
      setTruncated(false);
      setSaving(false);
      setEditorOpen(true);
    } catch {
      if (seq !== editSeqRef.current) return;
      message.error(t("skills.readFailed"));
    }
  };

  const handleSave = async () => {
    if (truncated) {
      // The editor only holds a truncated copy; saving would silently drop
      // the unread tail of the real SKILL.md.
      message.error(t("skills.contentTruncated"));
      return;
    }
    const skillName = name.trim();
    if (!skillName) {
      message.error(t("skills.nameRequired"));
      return;
    }
    if (!SKILL_NAME_RE.test(skillName)) {
      message.error(t("skills.nameInvalid"));
      return;
    }
    if (nameTaken) {
      message.error(t("skills.nameTaken"));
      return;
    }
    // Defense-in-depth, not a reachable flow: antd 6.5.0 returns early from
    // handleCancel while confirmLoading is set, so every cancel/close path is
    // blocked and the mask also covers the row actions. The captured sequence
    // still guards the state machine, so a later change that makes the modal
    // dismissible mid-save cannot let a late completion close a newer session
    // and discard its unsaved edits.
    const seq = editSeqRef.current;
    setSaving(true);
    try {
      await saveSkill(skillName, content, editingName !== "");
      message.success(t("skills.saveSuccess"));
      if (seq === editSeqRef.current) {
        setEditorOpen(false);
      }
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.saveFailed"),
      );
    } finally {
      if (seq === editSeqRef.current) {
        setSaving(false);
      }
    }
  };

  const handleToggle = async (item: SkillItem, enabled: boolean) => {
    try {
      await setSkillEnabled(item.name, enabled);
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.saveFailed"),
      );
    }
  };

  const handleDelete = (item: SkillItem) => {
    Modal.confirm({
      title: t("skills.deleteConfirmTitle"),
      content: item.name,
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteSkill(item.name);
          await refresh();
        } catch (error) {
          message.error(
            error instanceof Error ? error.message : t("skills.saveFailed"),
          );
        }
      },
    });
  };

  const handleUploadZip = () => fileInputRef.current?.click();

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }
    setUploading(true);
    try {
      const res = await uploadSkillZip(file);
      if (res.count > 0) {
        message.success(
          `${t("skills.uploadSuccess")}: ${res.imported.join(", ")}`,
        );
      } else {
        message.warning(t("skills.uploadNoSkill"));
      }
      if (res.skipped.length > 0) {
        const names = res.skipped.map((entry) => entry.name).join(", ");
        message.warning(`${t("skills.uploadSkipped")}: ${names}`);
      }
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    } finally {
      setUploading(false);
    }
  };

  const openUrlImport = () => {
    setUrlValue("");
    setUrlTarget("");
    setUrlOpen(true);
  };

  const handleImportUrl = async () => {
    const bundleUrl = urlValue.trim();
    if (!SKILL_URL_RE.test(bundleUrl)) {
      message.warning(t("skills.urlInvalid"));
      return;
    }
    const target = urlTarget.trim();
    // Defense-in-depth: the modal disables submit on both of these, so the
    // user already sees the reason inline before this can run.
    if (target && !SKILL_NAME_RE.test(target)) {
      message.error(t("skills.nameInvalid"));
      return;
    }
    // An optional name is still a create, so an occupied one is refused
    // rather than replaced; block it here instead of letting the user
    // discover it from the backend's 400.
    if (target && items.some((item) => item.name === target)) {
      message.error(t("skills.nameTaken"));
      return;
    }
    const seq = importSeqRef.current + 1;
    importSeqRef.current = seq;
    setImportingUrl(true);
    try {
      const res = await importSkillFromUrl(bundleUrl, target);
      message.success(`${t("skills.importUrlSuccess")}: ${res.name}`);
      if (res.renamed_from) {
        message.warning(
          t("skills.importUrlRenamed", {
            from: res.renamed_from,
            to: res.name,
          }),
        );
      }
      if (res.ignored_files > 0) {
        message.info(
          t("skills.importUrlIgnored", { count: res.ignored_files }),
        );
      }
      if (seq === importSeqRef.current) {
        setUrlOpen(false);
        setUrlValue("");
        setUrlTarget("");
      }
      await refresh();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.importUrlFailed"),
      );
    } finally {
      if (seq === importSeqRef.current) {
        setImportingUrl(false);
      }
    }
  };

  const nameInvalid =
    !editingName && name.trim().length > 0 && !SKILL_NAME_RE.test(name.trim());
  // Creating on an occupied name would replace that skill's SKILL.md; the
  // backend refuses it, so block the submit here and say why up front.
  const nameTaken =
    !editingName &&
    SKILL_NAME_RE.test(name.trim()) &&
    items.some((item) => item.name === name.trim());
  // The URL import takes an optional name, and supplying one makes it a
  // create under that name -- so the create dialog's rules apply verbatim.
  const urlTargetName = urlTarget.trim();
  const urlTargetInvalid =
    urlTargetName !== "" && !SKILL_NAME_RE.test(urlTargetName);
  const urlTargetTaken =
    !urlTargetInvalid && items.some((item) => item.name === urlTargetName);
  const urlReady =
    SKILL_URL_RE.test(urlValue.trim()) && !urlTargetInvalid && !urlTargetTaken;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: "var(--color-text-primary)",
            }}
          >
            {t("modelConfig.paneSkills")}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-tertiary)",
              marginTop: 3,
              lineHeight: 1.6,
            }}
          >
            {t("modelConfig.paneSkillsDesc")}
          </div>
        </div>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              {
                key: "create",
                label: t("skills.newSkill"),
                icon: <Plus size={14} />,
                onClick: openCreate,
              },
              {
                key: "upload",
                label: t("skills.uploadZip"),
                icon: <Upload size={14} />,
                onClick: handleUploadZip,
              },
              {
                key: "importUrl",
                label: t("skills.importUrl"),
                icon: <Globe size={14} />,
                onClick: openUrlImport,
              },
            ],
          }}
        >
          <Button icon={<Plus size={14} />} loading={uploading}>
            {t("skills.add")}
          </Button>
        </Dropdown>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
      </div>

      <div
        style={{
          borderLeft: "3px solid var(--color-accent)",
          background: "var(--color-bg-layout)",
          borderRadius: "0 8px 8px 0",
          padding: "7px 12px",
          fontSize: 11.5,
          lineHeight: 1.6,
          color: "var(--color-text-secondary)",
        }}
      >
        {t("skills.paneHint")}
      </div>

      {items.length === 0 && (
        <div
          style={{
            fontSize: 12,
            color: "var(--color-text-tertiary)",
            padding: "12px 0",
          }}
        >
          {t("skills.empty")}
        </div>
      )}

      {items.map((item) => (
        <div
          key={item.name}
          style={{
            border: "1px solid var(--color-border)",
            borderRadius: 10,
            padding: "10px 12px",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span>{item.name}</span>
              {item.builtin && (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 500,
                    color: "var(--color-text-tertiary)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 6,
                    padding: "0 5px",
                  }}
                >
                  {t("skills.builtin")}
                </span>
              )}
              {item.status === "unavailable" && (
                <Tooltip title={item.reason}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--color-warning)",
                    }}
                  >
                    {t("skills.unavailable")}
                  </span>
                </Tooltip>
              )}
            </div>
            <div
              style={{
                fontSize: 11.5,
                color: "var(--color-text-secondary)",
                marginTop: 2,
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 1,
                WebkitBoxOrient: "vertical" as const,
              }}
            >
              {briefDescription(item.description) || t("skills.noDescription")}
            </div>
          </div>
          <Switch
            size="small"
            checked={item.enabled}
            disabled={item.builtin}
            onChange={(checked) => handleToggle(item, checked)}
          />
          <Button
            size="small"
            type="text"
            aria-label={t("skills.preview")}
            icon={<Eye size={14} />}
            onClick={() => openPreview(item)}
          />
          {!item.builtin && (
            <>
              <Button
                size="small"
                type="text"
                aria-label={t("skills.edit")}
                icon={<Pencil size={14} />}
                onClick={() => openEdit(item)}
              />
              <Button
                size="small"
                type="text"
                danger
                aria-label={t("common.delete")}
                icon={<Trash2 size={14} />}
                onClick={() => handleDelete(item)}
              />
            </>
          )}
        </div>
      ))}

      <Modal
        open={editorOpen}
        title={
          previewMode
            ? `${t("skills.preview")} · ${editingName}`
            : editingName
            ? t("skills.edit")
            : t("skills.newSkill")
        }
        okText={t("common.save")}
        cancelText={previewMode ? t("common.close") : t("common.cancel")}
        okButtonProps={{
          style: previewMode ? { display: "none" } : undefined,
          disabled: truncated || nameTaken,
        }}
        confirmLoading={saving}
        onOk={handleSave}
        onCancel={() => setEditorOpen(false)}
        width={720}
        centered
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {!previewMode && (
            <div>
              <label className="field-label">{t("skills.name")}</label>
              <Input
                value={name}
                disabled={!!editingName || saving}
                status={nameInvalid || nameTaken ? "error" : undefined}
                placeholder="my-video-editing-skill"
                onChange={(event) => setName(event.target.value)}
              />
              {!editingName && (
                <div
                  style={{
                    fontSize: 11,
                    marginTop: 4,
                    lineHeight: 1.5,
                    color:
                      nameInvalid || nameTaken
                        ? "var(--color-error)"
                        : "var(--color-text-tertiary)",
                  }}
                >
                  {nameInvalid
                    ? t("skills.nameInvalid")
                    : nameTaken
                    ? t("skills.nameTaken")
                    : t("skills.nameRule")}
                </div>
              )}
            </div>
          )}
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 4,
              }}
            >
              <label className="field-label">{t("skills.content")}</label>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-tertiary)",
                  }}
                >
                  {t("skills.preview")}
                </span>
                <Switch
                  size="small"
                  checked={showPreview}
                  disabled={saving}
                  onChange={setShowPreview}
                />
              </div>
            </div>
            {showPreview ? (
              <div
                style={{
                  border: "1px solid var(--color-border)",
                  borderRadius: 8,
                  padding: "12px 16px",
                  height: 360,
                  overflow: "auto",
                  background: "var(--color-bg-layout)",
                  fontSize: 13,
                  lineHeight: 1.7,
                }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {stripFrontmatter(content)}
                </ReactMarkdown>
              </div>
            ) : (
              // Frozen while a save is in flight. The request carries the
              // content as of the click and success closes this same session,
              // so anything typed afterwards would be dropped silently;
              // editSeqRef tells sessions apart, not drafts inside one.
              <Input.TextArea
                rows={16}
                value={content}
                readOnly={previewMode || saving}
                onChange={(event) => setContent(event.target.value)}
              />
            )}
          </div>
          {!previewMode && (
            <div
              style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                lineHeight: 1.6,
              }}
            >
              {t("skills.editorHint")}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={urlOpen}
        title={t("skills.importUrlTitle")}
        okText={t("common.import")}
        cancelText={t("common.cancel")}
        okButtonProps={{ disabled: !urlReady }}
        confirmLoading={importingUrl}
        onOk={handleImportUrl}
        onCancel={() => setUrlOpen(false)}
        width={520}
        centered
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Frozen while an import is in flight, for the same reason as the
              editor body: the request carries these values as of the click and
              success closes this dialog and clears both, so a URL retyped
              during the wait would vanish without a word. */}
          <div>
            <label className="field-label">{t("skills.importUrlLabel")}</label>
            <Input
              value={urlValue}
              readOnly={importingUrl}
              placeholder="https://skills.sh/owner/repo/skill"
              onChange={(event) => setUrlValue(event.target.value)}
            />
            {!SKILL_URL_RE.test(urlValue.trim()) && (
              <div
                style={{
                  fontSize: 11,
                  marginTop: 4,
                  lineHeight: 1.5,
                  color:
                    urlValue.trim().length > 0
                      ? "var(--color-error)"
                      : "var(--color-text-tertiary)",
                }}
              >
                {t("skills.urlInvalid")}
              </div>
            )}
          </div>
          <div>
            <label className="field-label">
              {t("skills.importUrlNameLabel")}
            </label>
            <Input
              value={urlTarget}
              readOnly={importingUrl}
              placeholder={t("skills.importUrlNamePlaceholder")}
              onChange={(event) => setUrlTarget(event.target.value)}
            />
            <div
              style={{
                fontSize: 11,
                marginTop: 4,
                lineHeight: 1.5,
                color:
                  urlTargetInvalid || urlTargetTaken
                    ? "var(--color-error)"
                    : "var(--color-text-tertiary)",
              }}
            >
              {urlTargetInvalid
                ? t("skills.nameInvalid")
                : urlTargetTaken
                ? t("skills.nameTaken")
                : t("skills.importUrlNameHint")}
            </div>
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: "var(--color-text-tertiary)",
              lineHeight: 1.6,
            }}
          >
            {t("skills.importUrlHint")}
          </div>
        </div>
      </Modal>
    </div>
  );
}
