import { AutoComplete, Button, InputNumber, Input, Popconfirm } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type {
  ProjectEntityCollection,
  ShotDocument,
} from "@/contracts/creator";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";

const { TextArea } = Input;

// ShotDocument.camera / framing are free strings in the schema; these are
// presentation-only presets — any custom text still writes straight back.
const CAMERA_PRESETS = [
  "⊙ 静止",
  "→ 横移跟拍",
  "← 横移",
  "↗ 上摇",
  "↘ 下摇",
  "⇢ 推近",
  "⇠ 拉远",
  "◎ 环绕",
  "〰 手持晃动",
];
const FRAMING_PRESETS = [
  "远景",
  "全景",
  "中景",
  "近景",
  "特写",
  "仰拍近景",
  "俯拍",
  "过肩",
];
const CAMERA_OPTIONS = CAMERA_PRESETS.map((value) => ({ value }));
const FRAMING_OPTIONS = FRAMING_PRESETS.map((value) => ({ value }));

type ShotField = "description" | "camera" | "framing" | "duration_seconds";

interface ShotListProps {
  shots: ProjectEntityCollection<ShotDocument>;
  elementId: string;
  shotPointer: (shotId: string, field: ShotField) => string;
  disabled?: boolean;
  onChangeField: (shotId: string, field: ShotField, value: unknown) => void;
  onAdd: () => void;
  onDelete: (shot: ShotDocument) => void;
}

/** Controlled Shot editor; the parent stages fields before one explicit Apply. */
export default function ShotList({
  shots,
  elementId,
  shotPointer,
  disabled,
  onChangeField,
  onAdd,
  onDelete,
}: ShotListProps) {
  const { t } = useTranslation();
  const trackShotFocus = (shotId: string, field: ShotField) => {
    const store = useCreatorInteractionStore.getState();
    store.select(`element:${elementId}`);
    store.setEditingField(`element:${elementId}/shot:${shotId}/${field}`);
  };

  const releaseShotFocus = () => {
    useCreatorInteractionStore.getState().setEditingField(null);
  };

  return (
    <div className="space-y-2">
      {shots.order.map((shotId, index) => {
        const shot = shots.items[shotId];
        if (!shot) return null;
        return (
          <div
            key={shotId}
            data-creator-module="shot-row"
            data-creator-module-id={shotId}
            data-creator-module-ref={`element:${elementId}`}
            data-shot-index={index}
            className="space-y-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-2.5 transition-colors"
          >
            <div className="flex items-start gap-1">
              <span className="mt-[7px] w-4 shrink-0 text-right text-[10px] font-bold leading-3 text-[var(--color-text-tertiary)]">
                {index + 1}
              </span>
              <div
                className="min-w-0 flex-1"
                data-creator-field={`element:${elementId}/shot:${shotId}/description`}
                data-creator-path={shotPointer(shotId, "description")}
                data-creator-field-label={t("lib.shotDescription", {
                  index: index + 1,
                })}
              >
                <TextArea
                  value={shot.description}
                  disabled={disabled}
                  onChange={(event) =>
                    onChangeField(shotId, "description", event.target.value)
                  }
                  onFocus={() => trackShotFocus(shotId, "description")}
                  onBlur={releaseShotFocus}
                  autoSize={{ minRows: 1, maxRows: 6 }}
                  placeholder={t("workbench.shotDesc")}
                  className="!rounded-md !border-transparent !bg-transparent !p-1 !text-xs hover:!border-[var(--color-border)] focus:!border-[var(--color-accent)]"
                />
                <InlineReviewDiff
                  pointer={shotPointer(shotId, "description")}
                />
              </div>
              <Popconfirm
                title={t("workbench.deleteShot")}
                onConfirm={() => onDelete(shot)}
                okText={t("workbench.delete")}
                cancelText={t("workbench.cancel")}
              >
                <Button
                  type="text"
                  size="small"
                  disabled={disabled}
                  icon={<DeleteOutlined />}
                  className="!text-[var(--color-text-tertiary)] hover:!text-[var(--color-danger)]"
                />
              </Popconfirm>
            </div>
            <div className="grid grid-cols-[1.25fr_1fr_0.85fr] gap-1.5">
              <label
                data-creator-field={`element:${elementId}/shot:${shotId}/camera`}
                data-creator-path={shotPointer(shotId, "camera")}
                data-creator-field-label={t("lib.shotCamera", {
                  index: index + 1,
                })}
                className="min-w-0"
              >
                <span className="mb-0.5 block text-[10px] leading-3 text-[var(--color-text-tertiary)]">
                  {t("workbench.shotCameraLabel")}
                </span>
                <AutoComplete
                  value={shot.camera ?? ""}
                  disabled={disabled}
                  options={CAMERA_OPTIONS}
                  onChange={(value) =>
                    onChangeField(shotId, "camera", value ?? "")
                  }
                  onFocus={() => trackShotFocus(shotId, "camera")}
                  onBlur={releaseShotFocus}
                  size="small"
                  placeholder={t("workbench.shotCamera")}
                  className="!w-full !text-[11px]"
                />
              </label>
              <label
                data-creator-field={`element:${elementId}/shot:${shotId}/framing`}
                data-creator-path={shotPointer(shotId, "framing")}
                data-creator-field-label={t("lib.shotFraming", {
                  index: index + 1,
                })}
                className="min-w-0"
              >
                <span className="mb-0.5 block text-[10px] leading-3 text-[var(--color-text-tertiary)]">
                  {t("workbench.shotFraming")}
                </span>
                <AutoComplete
                  value={shot.framing ?? ""}
                  disabled={disabled}
                  options={FRAMING_OPTIONS}
                  onChange={(value) =>
                    onChangeField(shotId, "framing", value ?? "")
                  }
                  onFocus={() => trackShotFocus(shotId, "framing")}
                  onBlur={releaseShotFocus}
                  size="small"
                  placeholder={t("workbench.shotFraming")}
                  className="!w-full !text-[11px]"
                />
              </label>
              <label
                data-creator-field={`element:${elementId}/shot:${shotId}/duration_seconds`}
                data-creator-path={shotPointer(shotId, "duration_seconds")}
                data-creator-field-label={t("lib.shotDuration", {
                  index: index + 1,
                })}
                className="min-w-0"
              >
                <span className="mb-0.5 block text-[10px] leading-3 text-[var(--color-text-tertiary)]">
                  {t("workbench.shotDurationLabel")}
                </span>
                <InputNumber
                  min={1}
                  max={15}
                  value={shot.duration_seconds}
                  disabled={disabled}
                  onChange={(value) =>
                    onChangeField(shotId, "duration_seconds", value ?? 1)
                  }
                  onFocus={() => trackShotFocus(shotId, "duration_seconds")}
                  onBlur={releaseShotFocus}
                  size="small"
                  suffix="s"
                  controls={false}
                  className="!w-full"
                />
              </label>
            </div>
            <InlineReviewDiff pointer={shotPointer(shotId, "camera")} />
            <InlineReviewDiff pointer={shotPointer(shotId, "framing")} />
            <InlineReviewDiff
              pointer={shotPointer(shotId, "duration_seconds")}
            />
          </div>
        );
      })}
      <Button
        type="dashed"
        size="small"
        icon={<PlusOutlined />}
        onClick={onAdd}
        disabled={disabled}
        className="!w-full !text-xs"
      >
        {t("workbench.addShot")}
      </Button>
    </div>
  );
}
