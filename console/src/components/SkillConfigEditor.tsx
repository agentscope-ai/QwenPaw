import { Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { SkillRequirements } from "../api/types/skill";
import styles from "./SkillConfigEditor.module.less";

interface SkillConfigEditorProps {
  value: string;
  onChange: (value: string) => void;
  requirements?: SkillRequirements;
}

export function SkillConfigEditor({
  value,
  onChange,
  requirements,
}: SkillConfigEditorProps) {
  const { t } = useTranslation();
  const envs = requirements?.require_envs;
  const placeholder = envs?.length
    ? JSON.stringify(
        Object.fromEntries(envs.map((name) => [name, "..."])),
        null,
        2,
      )
    : "";

  return (
    <div className={styles.editor}>
      <Input.TextArea
        aria-label={t("skills.config")}
        rows={4}
        value={value.trim() === "{}" ? "" : value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
