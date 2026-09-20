import { InputNumber, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import type {
  ThinkingControlSpec,
  ThinkingLevel,
} from "@/features/thinking/types";

export function ThinkingCapabilityFields({
  value,
  onChange,
}: {
  value?: ThinkingControlSpec | null;
  onChange: (value: ThinkingControlSpec | null) => void;
}) {
  const { t } = useTranslation();
  const kind = value?.kind ?? "unknown";
  return (
    <details style={{ marginBlock: 12 }}>
      <summary style={{ cursor: "pointer", fontSize: 13 }}>
        {t("thinkingControl.declaration")}
      </summary>
      <p style={{ color: "var(--app-text-tertiary)", fontSize: 12 }}>
        {t("thinkingControl.declarationHint")}
      </p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        <Select
          aria-label={t("thinkingControl.controlType")}
          value={kind}
          options={["unknown", "unsupported", "effort", "budget"].map(
            (item) => ({
              value: item,
              label: t(`thinkingControl.type.${item}`),
            }),
          )}
          onChange={(next) =>
            onChange(
              next === "unknown"
                ? null
                : {
                    kind: next,
                    efforts: next === "effort" ? ["low", "medium", "high"] : [],
                    supports_off: false,
                    ...(next === "budget"
                      ? { budget_min: 1, budget_max: 8192 }
                      : {}),
                  },
            )
          }
        />
        {value && (kind === "budget" || kind === "effort") && (
          <>
            <Select
              aria-label={t("thinkingControl.wire")}
              value={value.wire ?? "native"}
              options={(kind === "budget"
                ? [
                    "native",
                    "compat_budget",
                    "anthropic_budget",
                    "gemini_budget",
                  ]
                : [
                    "native",
                    "compat_effort",
                    "anthropic_adaptive",
                    "gemini_level",
                  ]
              ).map((wire) => ({
                value: wire,
                label: t(`thinkingControl.wireType.${wire}`),
              }))}
              onChange={(wire) => onChange({ ...value, wire })}
            />
            {kind === "effort" ? (
              <Select
                mode="multiple"
                aria-label={t("thinkingControl.efforts")}
                value={value.efforts}
                options={[
                  "minimal",
                  "low",
                  "medium",
                  "high",
                  "xhigh",
                  "max",
                ].map((level) => ({
                  value: level,
                  label: t(`thinkingControl.${level}`),
                }))}
                onChange={(efforts: ThinkingLevel[]) =>
                  onChange({ ...value, efforts })
                }
              />
            ) : (
              <>
                <label>
                  {t("thinkingControl.minimum")}
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1}
                    precision={0}
                    value={value.budget_min}
                    onChange={(next) => {
                      if (next !== null)
                        onChange({
                          ...value,
                          budget_min: next,
                          budget_default: undefined,
                        });
                    }}
                  />
                </label>
                <label>
                  {t("thinkingControl.maximum")}
                  <InputNumber
                    style={{ width: "100%" }}
                    min={value.budget_min ?? 1}
                    precision={0}
                    value={value.budget_max}
                    onChange={(next) => {
                      if (next !== null)
                        onChange({
                          ...value,
                          budget_max: next,
                          budget_default: undefined,
                        });
                    }}
                  />
                </label>
              </>
            )}
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Switch
                size="small"
                checked={value.supports_off}
                onChange={(supports_off) =>
                  onChange({ ...value, supports_off })
                }
              />
              {t("thinkingControl.canDisable")}
            </label>
          </>
        )}
      </div>
    </details>
  );
}
