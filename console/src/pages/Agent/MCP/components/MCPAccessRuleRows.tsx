import React, { useEffect, useState } from "react";
import { DeleteOutlined } from "@ant-design/icons";
import { Button, Input, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type {
  MCPAccessEffect,
  MCPAccessRule,
  MCPAccessSubjectType,
} from "../../../../api/types";
import { MCP_CHANNEL_SOURCE_VALUES } from "../accessPolicy";
import styles from "../index.module.less";

interface RuleTextInputProps {
  value: string;
  placeholder: string;
  className: string;
  onCommit: (value: string) => void;
}

const RuleTextInput: React.FC<RuleTextInputProps> = ({
  value,
  placeholder,
  className,
  onCommit,
}) => {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  return (
    <Input
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => onCommit(draft)}
      onPressEnter={() => onCommit(draft)}
      placeholder={placeholder}
      className={className}
    />
  );
};

export function defaultSubjectValue(subjectType: MCPAccessSubjectType): string {
  return subjectType === "user" ? "default" : "";
}

const CHANNEL_SOURCE_OPTIONS: { label: string; value: string }[] =
  MCP_CHANNEL_SOURCE_VALUES.map((value) => ({
    label:
      {
        console: "Console",
        dingtalk: "DingTalk",
        feishu: "Feishu",
        wechat: "WeChat",
        wecom: "WeCom",
        discord: "Discord",
        telegram: "Telegram",
        qq: "QQ",
        imessage: "iMessage",
        mattermost: "Mattermost",
        matrix: "Matrix",
        onebot: "OneBot",
        mqtt: "MQTT",
        voice: "Voice",
        sip: "SIP",
        xiaoyi: "XiaoYi",
      }[value] || value,
    value,
  }));

function channelSourceOptions(
  allChannelsLabel: string,
): { label: string; value: string }[] {
  return [
    {
      label: allChannelsLabel,
      value: "*",
    },
    ...CHANNEL_SOURCE_OPTIONS,
  ];
}

interface MCPAccessRuleRowsProps<Rule extends MCPAccessRule> {
  rules: Rule[];
  getKey: (rule: Rule) => string;
  updateRule: (rule: Rule, patch: Partial<MCPAccessRule>) => void;
  setRuleEffect: (rule: Rule, effect: MCPAccessEffect) => void;
  deleteRule: (rule: Rule) => void;
  emptyText: string;
  effectLabel: (effect: MCPAccessEffect) => string;
}

export function MCPAccessRuleRows<Rule extends MCPAccessRule>({
  rules,
  getKey,
  updateRule,
  setRuleEffect,
  deleteRule,
  emptyText,
  effectLabel,
}: MCPAccessRuleRowsProps<Rule>) {
  const { t } = useTranslation();
  const sourceValueOptions = channelSourceOptions(
    t("mcp.access.sourceValueAllChannels"),
  );
  const subjectTypeOptions = [
    { label: t("mcp.access.subjectTypeOption.all"), value: "all" },
    { label: t("mcp.access.subjectTypeOption.user"), value: "user" },
  ];

  if (rules.length === 0) {
    return <div className={styles.accessNoRules}>{emptyText}</div>;
  }

  return (
    <div className={styles.accessRuleList}>
      {rules.map((rule) => (
        <div key={getKey(rule)} className={styles.accessRuleRow}>
          <div className={styles.accessRuleField}>
            <span className={styles.accessRuleFieldLabel}>
              {t("mcp.access.sourceValue")}
            </span>
            <Select
              className={styles.accessRuleSourceValue}
              value={rule.source_value}
              onChange={(sourceValue) =>
                updateRule(rule, {
                  source_value: String(sourceValue),
                })
              }
              options={sourceValueOptions}
            />
          </div>
          <div className={styles.accessRuleField}>
            <span className={styles.accessRuleFieldLabel}>
              {t("mcp.access.subjectType")}
            </span>
            <Select
              className={styles.accessRuleSubjectType}
              value={rule.subject_type}
              onChange={(value) =>
                updateRule(rule, {
                  subject_type: value as MCPAccessSubjectType,
                })
              }
              options={subjectTypeOptions}
            />
          </div>
          <div className={styles.accessRuleField}>
            <span className={styles.accessRuleFieldLabel}>
              {t("mcp.access.subjectValue")}
            </span>
            {rule.subject_type === "user" ? (
              <RuleTextInput
                value={rule.subject_value}
                placeholder={t("mcp.access.subjectValuePlaceholder")}
                className={styles.accessRuleSubjectValue}
                onCommit={(subjectValue) =>
                  updateRule(rule, {
                    subject_value: subjectValue,
                  })
                }
              />
            ) : (
              <Input
                className={styles.accessRuleSubjectValue}
                value={t("mcp.access.subjectValueAll")}
                disabled
              />
            )}
          </div>
          <div className={styles.accessRuleField}>
            <span className={styles.accessRuleFieldLabel}>
              {t("mcp.access.effectLabel")}
            </span>
            <Select
              className={styles.accessRuleEffect}
              value={rule.effect}
              onChange={(value) =>
                setRuleEffect(rule, value as MCPAccessEffect)
              }
              options={[
                { label: effectLabel("allow"), value: "allow" },
                { label: effectLabel("ask"), value: "ask" },
                { label: effectLabel("deny"), value: "deny" },
              ]}
            />
          </div>
          <Button
            className={styles.accessRuleDeleteButton}
            icon={<DeleteOutlined />}
            onClick={() => deleteRule(rule)}
            title={t("mcp.access.deleteRule")}
          />
        </div>
      ))}
    </div>
  );
}
