import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Popover } from "antd";
import { Ban, ChevronDown, Trash2 } from "lucide-react";
import type { VideoTemplateSummary } from "@/contracts/creator";
import { deleteVideoTemplate, listVideoTemplates } from "@/api/creator";
import thumbVlogDaily from "@/assets/design/style-thumbs/vlog_daily.jpg";
import thumbDramaCinematic from "@/assets/design/style-thumbs/short_drama_cinematic.jpg";
import thumbTutorialClean from "@/assets/design/style-thumbs/tutorial_clean.jpg";
import thumbInterviewPro from "@/assets/design/style-thumbs/interview_pro.jpg";
import thumbGamingNeon from "@/assets/design/style-thumbs/gaming_neon.jpg";
import thumbTravelWarm from "@/assets/design/style-thumbs/travel_warm.jpg";
import thumbProductShowcase from "@/assets/design/style-thumbs/product_showcase.jpg";

const BUILTIN_THUMBS: Record<string, string> = {
  vlog_daily: thumbVlogDaily,
  short_drama_cinematic: thumbDramaCinematic,
  tutorial_clean: thumbTutorialClean,
  interview_pro: thumbInterviewPro,
  gaming_neon: thumbGamingNeon,
  travel_warm: thumbTravelWarm,
  product_showcase: thumbProductShowcase,
};

interface VideoTemplatePickerProps {
  selectedTemplateId: string | null;
  onTemplateSelect: (templateId: string | null) => void;
}

const CARD_BASE =
  "relative h-[100px] w-[158px] cursor-pointer overflow-hidden rounded-lg transition-colors";

/** Toolbar pill that opens the style-preset card grid. */
export default function VideoTemplatePicker({
  selectedTemplateId,
  onTemplateSelect,
}: VideoTemplatePickerProps) {
  const { t } = useTranslation();
  const [templates, setTemplates] = useState<VideoTemplateSummary[]>([]);
  const [open, setOpen] = useState(false);

  const reload = useCallback(() => {
    listVideoTemplates()
      .then((res) => setTemplates(res.items ?? []))
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const selected = templates.find(
    (tpl) => tpl.templateId === selectedTemplateId,
  );
  const pillValue = selected ? selected.name : t("home.styleDefault");

  function choose(templateId: string | null) {
    onTemplateSelect(templateId);
    setOpen(false);
  }

  async function handleDelete(e: React.MouseEvent, tpl: VideoTemplateSummary) {
    e.stopPropagation();
    if (!window.confirm(t("home.deleteTemplateConfirm", { name: tpl.name })))
      return;
    try {
      await deleteVideoTemplate(tpl.templateId);
      if (selectedTemplateId === tpl.templateId) onTemplateSelect(null);
      reload();
    } catch {
      /* toast handled by API layer */
    }
  }

  function cardBorder(isSelected: boolean) {
    return isSelected
      ? "border-[1.5px] border-[var(--color-text-primary)]"
      : "border border-[var(--color-border)] hover:border-[var(--color-text-tertiary)]";
  }

  function renderTemplateCard(tpl: VideoTemplateSummary) {
    const isSelected = selectedTemplateId === tpl.templateId;
    const thumb =
      tpl.source === "builtin" ? BUILTIN_THUMBS[tpl.templateId] : undefined;
    return (
      <button
        key={tpl.templateId}
        type="button"
        data-style-card={tpl.templateId}
        data-style-selected={isSelected || undefined}
        onClick={() => choose(tpl.templateId)}
        className={`group ${CARD_BASE} ${cardBorder(isSelected)} ${
          thumb ? "" : "bg-[var(--color-bg-secondary)]"
        }`}
      >
        {thumb ? (
          <>
            <img
              src={thumb}
              alt=""
              className="absolute inset-0 h-full w-full object-cover"
            />
            <span className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-black/60 to-transparent" />
            <span className="absolute inset-x-2 bottom-2 truncate text-center text-[13px] font-medium text-white">
              {tpl.name}
            </span>
          </>
        ) : (
          <>
            <span className="absolute inset-x-0 top-6 text-center text-2xl leading-none">
              {tpl.iconEmoji}
            </span>
            <span className="absolute inset-x-2 bottom-2 truncate text-center text-[13px] text-[var(--color-text-secondary)]">
              {tpl.name}
            </span>
          </>
        )}
        {tpl.source === "user" && (
          <span
            role="button"
            tabIndex={-1}
            data-style-card-delete
            onClick={(e) => handleDelete(e, tpl)}
            className="absolute right-1 top-1 hidden h-5 w-5 items-center justify-center rounded-full bg-black/50 text-white group-hover:flex"
            aria-label={t("common.delete")}
          >
            <Trash2 className="h-3 w-3" />
          </span>
        )}
      </button>
    );
  }

  const panel = (
    <div
      data-style-popover
      className="w-[min(700px,calc(100vw-48px))] max-h-[min(60vh,520px)] overflow-y-auto p-1"
    >
      <div className="mb-3 text-sm font-semibold text-[var(--color-text-primary)]">
        {t("home.stylePillLabel")}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          data-style-card="default"
          data-style-selected={selectedTemplateId === null || undefined}
          onClick={() => choose(null)}
          className={`${CARD_BASE} bg-[var(--color-bg-secondary)] ${cardBorder(
            selectedTemplateId === null,
          )}`}
        >
          <Ban
            className="absolute left-1/2 top-6 h-8 w-8 -translate-x-1/2 text-[var(--color-text-primary)]"
            strokeWidth={1.5}
          />
          <span className="absolute inset-x-2 bottom-2 truncate text-center text-[13px] text-[var(--color-text-secondary)]">
            {t("home.styleDefault")}
          </span>
        </button>
        {templates.map(renderTemplateCard)}
      </div>
    </div>
  );

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomLeft"
      arrow={false}
      // Default overflow handling only flips, which throws the wide panel
      // past the viewport edge in small windows; shift keeps it on-screen.
      align={{
        overflow: { adjustX: false, adjustY: true, shiftX: true, shiftY: true },
      }}
      content={panel}
    >
      <button
        type="button"
        data-style-entry
        className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-full px-4 py-1 text-sm font-medium leading-6 text-[#656563] transition-colors hover:bg-[rgba(43,27,0,0.08)] hover:text-[var(--color-text-primary)] dark:text-[var(--color-text-secondary)] dark:hover:bg-white/10 ${
          open
            ? "bg-[rgba(43,27,0,0.08)] dark:bg-white/10"
            : "bg-[rgba(43,27,0,0.04)] dark:bg-white/5"
        }`}
      >
        {t("home.stylePillLabel")}: {pillValue}
        <ChevronDown className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" />
      </button>
    </Popover>
  );
}
