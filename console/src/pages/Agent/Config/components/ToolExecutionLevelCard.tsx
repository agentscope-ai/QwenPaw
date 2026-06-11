import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Shield, CheckCircle, AlertTriangle, Ban } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import styles from "../index.module.less";

export type ToolExecutionLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

interface LevelOption {
  value: ToolExecutionLevel;
  label: string;
  icon: React.ReactNode;
  description: string;
  color: string;
}

interface ToolExecutionLevelCardProps {
  value: ToolExecutionLevel;
  onChange: (level: ToolExecutionLevel) => void;
  disabled?: boolean;
}

export function ToolExecutionLevelCard({
  value: level,
  onChange,
  disabled = false,
}: ToolExecutionLevelCardProps) {
  const { t } = useTranslation();

  const levelOptions: LevelOption[] = [
    {
      value: "STRICT",
      label: t("agentConfig.toolExecutionLevel.strict"),
      icon: <Ban size={18} />,
      description: t("agentConfig.toolExecutionLevel.strictDesc"),
      color: "#ff4d4f",
    },
    {
      value: "SMART",
      label: t("agentConfig.toolExecutionLevel.smart"),
      icon: <AlertTriangle size={18} />,
      description: t("agentConfig.toolExecutionLevel.smartDesc"),
      color: "#faad14",
    },
    {
      value: "AUTO",
      label: t("agentConfig.toolExecutionLevel.auto"),
      icon: <Shield size={18} />,
      description: t("agentConfig.toolExecutionLevel.autoDesc"),
      color: "#1890ff",
    },
    {
      value: "OFF",
      label: t("agentConfig.toolExecutionLevel.off"),
      icon: <CheckCircle size={18} />,
      description: t("agentConfig.toolExecutionLevel.offDesc"),
      color: "#52c41a",
    },
  ];

  return (
    <Card className={styles.formCard}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield size={18} />
          {t("agentConfig.toolExecutionLevel.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-6 p-3 rounded-md bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 text-sm flex items-start gap-2">
          <Shield size={16} className="mt-0.5 shrink-0" />
          <span>{t("agentConfig.toolExecutionLevel.alertMessage")}</span>
        </div>

        <div className="space-y-4">
          {levelOptions.map((option) => (
            <Card
              key={option.value}
              className={cn(
                "cursor-pointer transition-all",
                styles.levelOptionCard,
                level === option.value ? "ring-2" : "ring-1 ring-border",
              )}
              style={{
                borderColor: level === option.value ? option.color : undefined,
                borderWidth: level === option.value ? 2 : 1,
                outline:
                  level === option.value
                    ? `2px solid ${option.color}`
                    : undefined,
                outlineOffset: -1,
              }}
              onClick={() => !disabled && onChange(option.value)}
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <input
                    type="radio"
                    checked={level === option.value}
                    onChange={() => !disabled && onChange(option.value)}
                    disabled={disabled}
                    className="mt-1"
                  />
                  <div
                    style={{ color: option.color }}
                    className="mt-0.5 shrink-0"
                  >
                    {option.icon}
                  </div>
                  <div>
                    <div className="font-semibold text-[15px]">
                      {option.label}
                    </div>
                    <p className="text-muted-foreground text-[13px] mt-1">
                      {option.description}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
