import React from "react";
import { Segmented } from "antd";
import type { MCPAccessEffect } from "../../../../api/types";
import styles from "../index.module.less";

const POLICY_SEGMENT_COLORS: Record<
  MCPAccessEffect,
  { bg: string; border: string; text: string }
> = {
  ask: {
    bg: "rgba(245, 158, 11, 0.24)",
    border: "rgba(217, 119, 6, 0.36)",
    text: "#8a4b00",
  },
  allow: {
    bg: "rgba(34, 197, 94, 0.22)",
    border: "rgba(22, 163, 74, 0.35)",
    text: "#17643a",
  },
  deny: {
    bg: "rgba(239, 68, 68, 0.2)",
    border: "rgba(220, 38, 38, 0.34)",
    text: "#9f1f26",
  },
};

function policySegmentStyle(effect: MCPAccessEffect): React.CSSProperties {
  const color = POLICY_SEGMENT_COLORS[effect];
  return {
    "--mcp-policy-segment-bg": color.bg,
    "--mcp-policy-segment-border": color.border,
    "--mcp-policy-segment-text": color.text,
  } as React.CSSProperties;
}

interface MCPAccessPolicySegmentedProps {
  value: MCPAccessEffect;
  onChange: (effect: MCPAccessEffect) => void;
  effectLabel: (effect: MCPAccessEffect) => string;
}

export const MCPAccessPolicySegmented: React.FC<
  MCPAccessPolicySegmentedProps
> = ({ value, onChange, effectLabel }) => (
  <Segmented
    className={styles.accessPolicySegmented}
    style={policySegmentStyle(value)}
    value={value}
    onChange={(nextValue) => onChange(nextValue as MCPAccessEffect)}
    options={[
      { label: effectLabel("ask"), value: "ask" },
      { label: effectLabel("allow"), value: "allow" },
      { label: effectLabel("deny"), value: "deny" },
    ]}
  />
);
