import { Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

interface ChartFilterSelectProps<T extends string> {
  value: T[];
  onChange: (values: T[]) => void;
  options: T[];
  placeholder: string;
  style?: React.CSSProperties;
}

export function ChartFilterSelect<T extends string>({
  value,
  onChange,
  options,
  placeholder,
  style,
}: ChartFilterSelectProps<T>) {
  const { t } = useTranslation();

  return (
    <Select
      mode="multiple"
      placeholder={placeholder}
      value={value}
      onChange={onChange}
      style={style}
      maxTagCount={0}
      maxTagPlaceholder={(omittedValues) => {
        return omittedValues.length === options.length
          ? t("tokenUsage.allSelected")
          : omittedValues.length === 0
          ? t("tokenUsage.itemsSelected", { count: 0 })
          : t("tokenUsage.itemsSelected", {
              count: omittedValues.length,
            });
      }}
      dropdownRender={(menu) => (
        <>
          <div
            style={{
              padding: "8px 12px",
              cursor: "pointer",
              borderBottom: "1px solid #f0f0f0",
              fontWeight: 500,
            }}
            onClick={() => onChange(options)}
          >
            {t("tokenUsage.selectAll")}
          </div>
          {menu}
        </>
      )}
      options={options.map((option) => ({
        label: option,
        value: option,
      }))}
    />
  );
}
