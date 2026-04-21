/**
 * Controlled multi-select for agent IDs used inside BackupScopeForm.
 * Injects a "__all__" sentinel as the first option to toggle all agents
 * at once. Uses Ant Design's virtual scrolling so lists with thousands
 * of agents don't cause DOM performance issues.
 */
import { Checkbox, Select } from "antd";
import type { BaseOptionType } from "antd/es/select";
import { useTranslation } from "react-i18next";
import type { AgentSummary } from "@/api/types/agents";

interface Props {
  agents: AgentSummary[];
  value: string[];
  onChange: (ids: string[]) => void;
}

/**
 * Multi-select for agent IDs with a "__all__" sentinel option that
 * toggles all agents at once. Uses virtual scrolling for large lists.
 */
export default function AgentMultiSelect({ agents, value, onChange }: Props) {
  const { t } = useTranslation();

  const allSelected = agents.length > 0 && value.length === agents.length;

  /**
   * Intercepts the "__all__" sentinel: clicking it either selects every agent
   * or clears the selection depending on the current allSelected state.
   */
  const handleChange = (vals: string[]) => {
    if (vals.includes("__all__")) {
      onChange(allSelected ? [] : agents.map((a) => a.id));
    } else {
      onChange(vals);
    }
  };

  const options = [
    {
      value: "__all__",
      label: allSelected ? t("backup.deselectAll") : t("backup.selectAll"),
    },
    ...agents.map((a) => ({ value: a.id, label: `${a.name} (${a.id})` })),
  ];

  // Render each option with a visual checkbox; pointerEvents:none prevents
  // the inner Checkbox from swallowing the click (Select handles the toggle).
  const optionRender = (option: BaseOptionType) => {
    const isAll = option.data.value === "__all__";
    const checked = isAll
      ? allSelected
      : value.includes(option.data.value as string);
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Checkbox checked={checked} style={{ pointerEvents: "none" }} />
        <span>{option.data.label}</span>
      </div>
    );
  };

  return (
    <Select
      mode="multiple"
      style={{ width: "100%" }}
      placeholder={t("backup.agentsPlaceholder")}
      value={value}
      onChange={handleChange}
      options={options}
      maxTagCount="responsive"
      allowClear
      showSearch
      optionFilterProp="label"
      virtual
      listHeight={256}
      optionRender={optionRender}
    />
  );
}
