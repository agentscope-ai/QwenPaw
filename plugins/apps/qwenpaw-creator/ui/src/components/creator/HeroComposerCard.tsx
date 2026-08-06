import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, Select, Tooltip } from "antd";
import type { InputRef } from "antd";
import {
  EyeOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import { ArrowUp, X } from "lucide-react";
import addFileIcon from "@/assets/design/icon-add-file.svg";
import addFolderIcon from "@/assets/design/icon-add-folder.svg";
import addLinkIcon from "@/assets/design/icon-add-link.svg";
import modelConfigIcon from "@/assets/design/icon-model-config.svg";
import {
  AUTO_PROJECT_NAME_LENGTH,
  SCENARIO_OPTIONS,
  SCENARIO_TERMS,
  CONTENT_TYPE_OPTIONS,
  chipLabel,
  useProjectLaunch,
} from "./useProjectLaunch";
import ModelConfigModal from "./ModelConfigModal";

const { TextArea } = Input;

/** Inline hero composer on the redesigned home page. */
export default function HeroComposerCard() {
  const { t } = useTranslation();
  const launch = useProjectLaunch();
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
  const [urlInputOpen, setUrlInputOpen] = useState(false);
  const urlInputRef = useRef<InputRef>(null);

  const pillSelectClassNames = {
    content:
      "!mr-0 !w-full !-translate-x-0.5 !justify-center !text-center !text-xs !font-semibold !text-[var(--color-text-secondary)]",
    suffix:
      "!absolute !right-2 !text-[10px] !text-[var(--color-text-tertiary)]",
    popup: {
      listItem: "!text-xs !font-semibold !text-[var(--color-text-secondary)]",
    },
  } as const;

  const contentTypeSelectClassNames = {
    content:
      "!mr-1 !text-sm !font-medium !leading-6 !text-[var(--color-text-primary)]",
    popup: {
      listItem: "!text-sm !text-[var(--color-text-primary)]",
    },
  } as const;

  return (
    <div
      data-onboarding-id="create-project"
      className="hero-composer-card w-full rounded-[8px] border border-[#EAE9E7] bg-white"
    >
      <div className="px-5 pt-4">
        {/* 2px dashed border: Chrome derives the dash length from the width,
           and a hairline reads too faint next to the solid hairlines. */}
        <div
          className={`rounded-[8px] border-2 border-dashed transition-colors ${
            dragOver
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
              : "border-[#B8B6B6] bg-white"
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
            placeholder={t("home.modelName", {
              count: AUTO_PROJECT_NAME_LENGTH,
            })}
            className="!rounded-none !border-x-0 !border-t-0 !border-b-[#EAE9E7] !bg-transparent !px-4 !py-3 !text-sm !leading-6 !shadow-none focus:!shadow-none"
          />
          <TextArea
            value={projectDescription}
            onChange={(e) => setProjectDescription(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 10 }}
            placeholder={t(SCENARIO_TERMS[scenario].descriptionKey)}
            className="!border-none !bg-transparent !px-4 !pb-2 !pt-3 !text-sm !leading-6 !shadow-none focus:!shadow-none"
          />

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {attachments.map((att) => {
                const { tag, name } = chipLabel(att);
                return (
                  <span
                    key={att.id}
                    className="inline-flex max-w-[260px] items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)] py-1 pl-2 pr-1 text-[11px] text-[var(--color-text-secondary)]"
                  >
                    <b className="shrink-0 text-[10px] text-[var(--color-accent)]">
                      {tag}
                    </b>
                    <span className="min-w-0 truncate">{name}</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full hover:bg-[var(--color-border)]"
                      aria-label={t("home.removeAttachment")}
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
              onClick={() => setModelConfigModalOpen(true)}
              className="flex w-full flex-wrap items-center gap-2 border-t border-[var(--color-warning)]/30 bg-[var(--color-warning-soft)]/40 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]/70"
            >
              <span className="text-[11px] font-medium text-[var(--color-warning)]">
                {t("home.requiredModelNotConfigured")}
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
                {t("home.clickToConfigure")}
              </span>
            </button>
          )}

          <div className="flex flex-wrap items-center gap-6 p-2">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm font-medium text-[var(--color-text-primary)] transition-opacity hover:opacity-70"
            >
              <img src={addFileIcon} alt="" width={24} height={24} />
              {t("home.addFile")}
            </button>
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
            <button
              type="button"
              onClick={() => folderInputRef.current?.click()}
              className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm font-medium text-[var(--color-text-primary)] transition-opacity hover:opacity-70"
            >
              <img src={addFolderIcon} alt="" width={24} height={24} />
              {t("home.addFolder")}
            </button>
            <input
              ref={folderInputRef}
              type="file"
              multiple
              hidden
              {...{ webkitdirectory: "", directory: "" }}
              onChange={(e) => {
                if (e.target.files?.length) addFiles(e.target.files, "folder");
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => {
                setUrlInputOpen((open) => !open);
                window.setTimeout(() => urlInputRef.current?.focus(), 0);
              }}
              className={`flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm font-medium transition-opacity hover:opacity-70 ${
                urlInputOpen || urlDraft
                  ? "text-[var(--color-accent)]"
                  : "text-[var(--color-text-primary)]"
              }`}
            >
              <img src={addLinkIcon} alt="" width={24} height={24} />
              {t("home.addLink")}
            </button>
            {urlInputOpen && (
              <Input
                ref={urlInputRef}
                size="small"
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                onPressEnter={addUrl}
                onBlur={() => {
                  if (!urlDraft.trim()) setUrlInputOpen(false);
                }}
                placeholder={t("home.pasteUrlAndEnter")}
                className="!w-[240px] !rounded-full !border-[var(--color-border)] !bg-[var(--color-bg-secondary)] !px-3 !text-xs !shadow-none"
              />
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3 px-5 py-4">
        <div
          role="radiogroup"
          aria-label={t("home.projectScenario")}
          className="flex items-center rounded-full bg-[rgba(43,27,0,0.04)] p-1"
        >
          {SCENARIO_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={scenario === option.key}
              onClick={() => handleScenarioChange(option.key)}
              className={`cursor-pointer rounded-full px-3 py-1 text-sm font-medium leading-6 transition-colors ${
                scenario === option.key
                  ? "bg-white text-[#332F2E] shadow-sm"
                  : "text-[#656563] hover:text-[var(--color-text-primary)]"
              }`}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>

        {/* Content type is only meaningful for the video_edit scenario. */}
        {isVideoEdit && (
          <div className="flex items-center gap-1 rounded-full bg-[rgba(43,27,0,0.04)] py-1 pl-4 pr-2">
            <span className="text-sm font-medium leading-6 text-[#656563]">
              {t("home.contentType")}
              <sup className="text-[var(--color-accent)]">*</sup>:
            </span>
            <Select
              aria-label={t("home.contentType")}
              size="small"
              value={contentType}
              onChange={setContentType}
              placeholder={t("home.pleaseSelect")}
              options={CONTENT_TYPE_OPTIONS.map((option) => ({
                value: option.key,
                label: t(option.labelKey),
              }))}
              popupMatchSelectWidth={false}
              variant="borderless"
              className="!h-6 !w-auto min-w-[76px]"
              classNames={contentTypeSelectClassNames}
            />
          </div>
        )}

        {!isVideoEdit && (
          <>
            <Select
              aria-label={t("home.resolution")}
              size="small"
              value={resolution}
              onChange={setResolution}
              options={[
                { value: "720P", label: "720P" },
                { value: "1080P", label: "1080P" },
              ]}
              popupMatchSelectWidth={false}
              variant="borderless"
              className="!h-8 !w-auto min-w-[84px] !rounded-full !bg-[rgba(43,27,0,0.04)]"
              classNames={pillSelectClassNames}
            />
            <Select
              aria-label={t("home.aspectRatio")}
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
              variant="borderless"
              className="!h-8 !w-auto min-w-[84px] !rounded-full !bg-[rgba(43,27,0,0.04)]"
              classNames={pillSelectClassNames}
            />
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            data-onboarding-id="model-config"
            onClick={() => setModelConfigModalOpen(true)}
            className="flex cursor-pointer items-center gap-1 rounded-full bg-[rgba(43,27,0,0.04)] px-4 py-1 text-sm font-medium leading-6 text-[#656563] transition-colors hover:bg-[rgba(43,27,0,0.08)] hover:text-[var(--color-text-primary)]"
          >
            <img src={modelConfigIcon} alt="" width={20} height={20} />
            {t("home.modelConfig")}
          </button>
          <Tooltip title={canLaunch ? undefined : launchHint()}>
            <button
              type="button"
              aria-label={t("home.launchAgent")}
              disabled={!canLaunch}
              onClick={handleLaunch}
              className={`flex h-8 w-8 items-center justify-center rounded-md transition-all ${
                canLaunch
                  ? "cursor-pointer bg-[var(--color-accent)] text-white shadow-[0_6px_16px_-6px_rgba(255,106,0,0.7)] hover:bg-[var(--color-accent-hover)]"
                  : "cursor-not-allowed bg-[rgba(43,27,0,0.06)] text-[rgba(26,23,22,0.35)]"
              }`}
            >
              {launching ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                <ArrowUp className="h-5 w-5" />
              )}
            </button>
          </Tooltip>
        </div>
      </div>

      <ModelConfigModal
        open={modelConfigModalOpen}
        onClose={() => {
          setModelConfigModalOpen(false);
          refreshModelConfig();
        }}
      />
    </div>
  );
}
