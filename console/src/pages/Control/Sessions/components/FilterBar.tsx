import { Input, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FilterBarProps {
  filterUserId: string;
  filterChannel: string;
  uniqueChannels: string[];
  onUserIdChange: (value: string) => void;
  onChannelChange: (value: string) => void;
}

export function FilterBar({
  filterUserId,
  filterChannel,
  uniqueChannels,
  onUserIdChange,
  onChannelChange,
}: FilterBarProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.filterBar}>
      <Input
        placeholder={t("sessions.filterUserId")}
        value={filterUserId}
        onChange={(e) => onUserIdChange(e.target.value)}
        allowClear
        className="sessions-filter-input"
        style={{ width: 200, marginRight: 8 }}
      />
      <Select
        placeholder={t("sessions.filterChannel")}
        value={filterChannel || undefined}
        onChange={(value) => onChannelChange(value || "")}
        allowClear
        className="sessions-filter-select"
        style={{ width: 180 }}
      >
        {uniqueChannels.map((channel) => (
          <Select.Option key={channel} value={channel}>
            {channel}
          </Select.Option>
        ))}
      </Select>
    </div>
  );
}
