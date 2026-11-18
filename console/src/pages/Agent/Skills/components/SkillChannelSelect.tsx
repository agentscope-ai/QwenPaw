import type { AriaAttributes } from "react";
import { Select } from "@agentscope-ai/design";
import { Button } from "antd";
import { useTranslation } from "react-i18next";

export interface SkillChannelOptions {
  options: { value: string; label: string }[];
  loading: boolean;
  loaded: boolean;
  error: boolean;
  onRetry: () => void;
}

interface Props extends AriaAttributes, SkillChannelOptions {
  value?: string[];
  onChange?: (value: string[]) => void;
  id?: string;
}

/** Controlled Skill scope input; discovery and persistence belong to the caller. */
export function SkillChannelSelect({
  value = [],
  onChange,
  options: availableOptions,
  loading,
  loaded,
  error,
  onRetry,
  id,
  ...ariaProps
}: Props) {
  const { t } = useTranslation();
  const known = new Set(availableOptions.map((option) => option.value));
  const missing = value.filter((key) => key !== "all" && !known.has(key));
  const options = [
    { value: "all", label: t("skills.allChannels") },
    ...availableOptions,
    ...missing.map((key) => ({
      value: key,
      label:
        loaded && !loading && !error
          ? `${key} (${t("skills.channelUnavailable")})`
          : key,
    })),
  ];

  return (
    <div>
      <Select
        {...ariaProps}
        id={id}
        mode="multiple"
        style={{ width: "100%" }}
        value={value}
        options={options}
        showSearch
        loading={loading}
        disabled={error || (loading && !loaded)}
        placeholder={t("skills.selectChannels")}
        filterOption={(input, option) =>
          `${option?.label ?? ""} ${option?.value ?? ""}`
            .toLocaleLowerCase()
            .includes(input.toLocaleLowerCase())
        }
        onChange={(next: string[]) => {
          const added = next.find((key) => !value.includes(key));
          onChange?.(
            added === "all" ? ["all"] : next.filter((key) => key !== "all"),
          );
        }}
      />
      {error && (
        <div role="status">
          {t("skills.channelsLoadFailed")}
          <Button type="link" size="small" onClick={onRetry}>
            {t("common.retry")}
          </Button>
        </div>
      )}
    </div>
  );
}
