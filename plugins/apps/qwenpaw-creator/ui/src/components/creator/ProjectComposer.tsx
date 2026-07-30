import { Button, Input, Modal, Select, Tooltip } from "antd";
import {
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  FileText,
  Film,
  FolderOpen,
  Link2,
  Paperclip,
  Rocket,
  X,
} from "lucide-react";
import {
  AUTO_PROJECT_NAME_LENGTH,
  MODES,
  SCENARIO_OPTIONS,
  SCENARIO_TERMS,
  CONTENT_TYPE_OPTIONS,
  chipLabel,
  useProjectLaunch,
} from "./useProjectLaunch";
import ModelConfigModal from "./ModelConfigModal";

const { TextArea } = Input;

export { SCENARIO_OPTIONS, CONTENT_TYPE_OPTIONS };

interface ProjectComposerProps {
  open: boolean;
  onClose: () => void;
}

export function ProjectComposer({ open, onClose }: ProjectComposerProps) {
  const launch = useProjectLaunch({ onLaunched: onClose });
  const {
    projectName,
    setProjectName,
    projectDescription,
    setProjectDescription,
    scenario,
    handleScenarioChange,
    contentType,
    setContentType,
    resolution,
    setResolution,
    aspectRatio,
    setAspectRatio,
    attachments,
    addFiles,
    addUrl,
    removeAttachment,
    urlDraft,
    setUrlDraft,
    launching,
    dragOver,
    setDragOver,
    fileInputRef,
    folderInputRef,
    modelConfigModalOpen,
    setModelConfigModalOpen,
    refreshModelConfig,
    missingRequiredModels,
    hasMissingModels,
    isVideoEdit,
    canLaunch,
    launchHint,
    handleLaunch,
  } = launch;

  return (
    <Modal
      open={open}
      onCancel={launching ? undefined : onClose}
      footer={null}
      width={720}
      centered
      closable={false}
      destroyOnHidden
      title={null}
    >
      <div className="pt-2">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-[var(--color-text-primary)]">
              <Film className="h-5 w-5 text-[var(--color-accent)]" />
              把目标、素材和限制交给 Agent
            </h2>
            <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
              资料输入是一次性的启动动作。进入项目后，它们会变成可管理、可引用、可追踪的项目资产。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <div className="flex items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-1">
              {MODES.map((mode) => (
                <Tooltip
                  key={mode.key}
                  title={mode.enabled ? undefined : "即将推出"}
                >
                  <button
                    type="button"
                    disabled={!mode.enabled}
                    aria-pressed={mode.key === "agent"}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                      mode.enabled
                        ? "bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] shadow-sm"
                        : "cursor-not-allowed text-[var(--color-text-tertiary)]"
                    }`}
                  >
                    {mode.label}
                  </button>
                </Tooltip>
              ))}
            </div>
            {!launching && (
              <button
                type="button"
                onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--color-text-tertiary)] transition-colors hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text-primary)]"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Benchmark scenario picker (5.5): drives the structure template, default
            style and the UI terminology throughout. */}
        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-[var(--color-text-tertiary)]">
            视频场景
          </span>
          {SCENARIO_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => handleScenarioChange(option.key)}
              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                scenario === option.key
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
              }`}
            >
              {option.label}
            </button>
          ))}
          {!isVideoEdit && (
            <div className="ml-auto flex items-center gap-2">
              <Select
                aria-label="分辨率"
                size="small"
                value={resolution}
                onChange={setResolution}
                options={[
                  { value: "720P", label: "720P" },
                  { value: "1080P", label: "1080P" },
                ]}
                popupMatchSelectWidth={false}
                className="!relative !h-7 !w-auto min-w-[76px] !rounded-full !border-[var(--color-border)] !bg-[var(--color-bg-secondary)]"
                classNames={{
                  content:
                    "!mr-0 !w-full !-translate-x-0.5 !justify-center !text-center !text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  suffix:
                    "!absolute !right-2 !text-[10px] !text-[var(--color-text-tertiary)]",
                  popup: {
                    listItem:
                      "!text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  },
                }}
              />
              <Select
                aria-label="宽高比"
                size="small"
                value={aspectRatio}
                onChange={setAspectRatio}
                options={[
                  { value: "16:9", label: "16:9" },
                  { value: "9:16", label: "9:16" },
                  { value: "1:1", label: "1:1" },
                  { value: "4:3", label: "4:3" },
                  { value: "3:4", label: "3:4" },
                ]}
                popupMatchSelectWidth={false}
                className="!relative !h-7 !w-auto min-w-[76px] !rounded-full !border-[var(--color-border)] !bg-[var(--color-bg-secondary)]"
                classNames={{
                  content:
                    "!mr-0 !w-full !-translate-x-0.5 !justify-center !text-center !text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  suffix:
                    "!absolute !right-2 !text-[10px] !text-[var(--color-text-tertiary)]",
                  popup: {
                    listItem:
                      "!text-[11px] !font-semibold !text-[var(--color-text-secondary)]",
                  },
                }}
              />
            </div>
          )}
        </div>

        <div
          className={`mt-3 rounded-xl border-2 border-dashed transition-colors ${
            dragOver
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
              : "border-[#B0AEAB]"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files.length > 0)
              addFiles(e.dataTransfer.files, "file");
          }}
        >
          <Input
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder={`项目名称（选填，留空则取目标描述前 ${AUTO_PROJECT_NAME_LENGTH} 字）`}
            className="!rounded-none !border-x-0 !border-t-0 !bg-transparent !text-sm !font-semibold !shadow-none focus:!shadow-none"
          />
          <TextArea
            value={projectDescription}
            onChange={(e) => setProjectDescription(e.target.value)}
            autoSize={{ minRows: 5, maxRows: 12 }}
            placeholder={"目标描述：" + SCENARIO_TERMS[scenario].description}
            className="!border-none !bg-transparent !p-4 !text-sm !shadow-none focus:!shadow-none"
          />

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {attachments.map((att) => {
                const { tag, name } = chipLabel(att);
                return (
                  <span
                    key={att.id}
                    className="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] py-1 pl-2 pr-1 text-[11px] text-[var(--color-text-secondary)]"
                  >
                    <b className="shrink-0 text-[10px] text-[var(--color-accent)]">
                      {tag}
                    </b>
                    <span className="min-w-0 truncate">{name}</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-[var(--color-border)]"
                      aria-label="移除附件"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          {hasMissingModels && (
            <button
              type="button"
              onClick={() => {
                setModelConfigModalOpen(true);
              }}
              className="flex flex-wrap items-center gap-2 border-t border-[var(--color-warning)]/30 bg-[var(--color-warning-soft)]/40 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]/70"
            >
              <span className="text-[11px] font-medium text-[var(--color-warning)]">
                必选模型未配置：
              </span>
              {missingRequiredModels!.map((type) => {
                const meta = {
                  vlm: {
                    label: "VLM",
                    icon: <EyeOutlined style={{ fontSize: 10 }} />,
                  },
                  image: {
                    label: "Image",
                    icon: <PictureOutlined style={{ fontSize: 10 }} />,
                  },
                  video: {
                    label: "Video",
                    icon: <VideoCameraOutlined style={{ fontSize: 10 }} />,
                  },
                }[type] ?? { label: type, icon: null };
                return (
                  <span
                    key={type}
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--color-warning)]/40 bg-white/60 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-warning)]"
                  >
                    {meta.icon}
                    {meta.label}
                  </span>
                );
              })}
              <span className="ml-auto text-[11px] font-semibold text-[var(--color-accent)]">
                点击配置 →
              </span>
            </button>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] px-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <Button
                size="small"
                type="text"
                icon={<Paperclip className="h-3.5 w-3.5" />}
                onClick={() => fileInputRef.current?.click()}
                className="!text-xs !text-[var(--color-text-secondary)]"
              >
                添加文件
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  if (e.target.files?.length) addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
              <Button
                size="small"
                type="text"
                icon={<FolderOpen className="h-3.5 w-3.5" />}
                onClick={() => folderInputRef.current?.click()}
                className="!text-xs !text-[var(--color-text-secondary)]"
              >
                选择文件夹
              </Button>
              <input
                ref={folderInputRef}
                type="file"
                multiple
                hidden
                {...{ webkitdirectory: "", directory: "" }}
                onChange={(e) => {
                  if (e.target.files?.length)
                    addFiles(e.target.files, "folder");
                  e.target.value = "";
                }}
              />
              <div className="flex min-w-0 flex-1 items-center gap-1">
                <Link2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)]" />
                <Input
                  size="small"
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onPressEnter={addUrl}
                  placeholder="粘贴 URL 后回车"
                  className="!max-w-[240px] !border-none !bg-transparent !text-xs !shadow-none"
                />
              </div>
            </div>
            <Tooltip title={canLaunch ? undefined : launchHint()}>
              <Button
                type="primary"
                icon={<Rocket className="h-3.5 w-3.5" />}
                disabled={!canLaunch}
                loading={launching}
                onClick={handleLaunch}
                className="!flex !items-center !gap-1.5 !font-semibold"
              >
                启动 Agent
              </Button>
            </Tooltip>
          </div>
          {isVideoEdit && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] px-3 py-2">
              <span className="text-[11px] font-medium text-[var(--color-text-tertiary)]">
                内容类型<sup className="text-[var(--color-accent)]">*</sup>
              </span>
              {CONTENT_TYPE_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setContentType(option.key)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    contentType === option.key
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <p className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--color-text-tertiary)]">
          <FileText className="h-3 w-3" />
          附件将进入资产库「用户上传」分类。
        </p>
      </div>
      <ModelConfigModal
        open={modelConfigModalOpen}
        onClose={() => {
          setModelConfigModalOpen(false);
          refreshModelConfig();
        }}
      />
    </Modal>
  );
}
