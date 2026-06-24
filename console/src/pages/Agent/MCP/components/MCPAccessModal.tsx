import React, { useEffect, useMemo, useState } from "react";
import { Button, Empty, Modal } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import type {
  MCPAccessEffect,
  MCPAccessPolicy,
  MCPAccessPrincipalOption,
  MCPAccessRule,
  MCPClientInfo,
  MCPToolAccessOverride,
  MCPToolInfo,
} from "../../../../api/types";
import {
  addClientRule,
  addToolRule,
  buildMCPAccessToolGroups,
  findMCPAccessPolicyWarning,
  normalizeMCPAccessPolicy,
  removeClientRule,
  removeToolRule,
  upsertClientRule,
  upsertToolDefault,
  upsertToolRule,
  validateMCPAccessPolicy,
} from "../accessPolicy";
import styles from "../index.module.less";
import { MCPAccessClientPanel } from "./MCPAccessClientPanel";
import { MCPAccessToolPanel } from "./MCPAccessToolPanel";

interface MCPAccessModalProps {
  client: MCPClientInfo;
  open: boolean;
  onClose: () => void;
  onSave: (policy: MCPAccessPolicy) => Promise<boolean>;
}

export const MCPAccessModal: React.FC<MCPAccessModalProps> = ({
  client,
  open,
  onClose,
  onSave,
}) => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [policy, setPolicy] = useState<MCPAccessPolicy | null>(null);
  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [principalOptions, setPrincipalOptions] = useState<
    MCPAccessPrincipalOption[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toolsError, setToolsError] = useState("");
  const [initialPolicySignature, setInitialPolicySignature] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setTools([]);
      setPrincipalOptions([]);
      setToolsError("");
      try {
        const savedPolicy = await api.getMCPPolicy(client.key);
        if (!cancelled) {
          const normalized = normalizeMCPAccessPolicy(savedPolicy);
          setPolicy(normalized);
          setInitialPolicySignature(policySignature(normalized));
        }

        try {
          const principals = await api.listMCPAccessPrincipals();
          if (!cancelled) {
            setPrincipalOptions(principals);
          }
        } catch {
          if (!cancelled) {
            setPrincipalOptions([]);
          }
        }

        if (!client.enabled) {
          if (!cancelled) {
            setToolsError(t("mcp.access.disabledTools"));
          }
          return;
        }

        try {
          const currentTools = await api.listMCPTools(client.key);
          if (!cancelled) {
            setTools(currentTools);
          }
        } catch (err: any) {
          if (!cancelled) {
            setToolsError(err?.message || t("mcp.toolsLoadError"));
          }
        }
      } catch {
        if (!cancelled) {
          setPolicy(null);
          setInitialPolicySignature("");
          setToolsError(t("mcp.access.loadError"));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [open, client.key, client.enabled, t]);

  const groups = useMemo(
    () => (policy ? buildMCPAccessToolGroups(tools, policy) : []),
    [tools, policy],
  );
  const isDirty = useMemo(
    () => Boolean(policy && policySignature(policy) !== initialPolicySignature),
    [policy, initialPolicySignature],
  );

  const effectLabel = (effect: MCPAccessEffect) =>
    t(`mcp.access.effect.${effect}`);

  const setDefaultEffect = (effect: MCPAccessEffect) => {
    setPolicy((prev) =>
      prev
        ? {
            ...prev,
            default_effect: effect,
          }
        : prev,
    );
  };

  const updateClientRule = (
    rule: MCPAccessRule,
    patch: Partial<MCPAccessRule>,
  ) => {
    const nextRule = withRuleDefaults(rule, patch);
    setPolicy((prev) =>
      prev
        ? upsertClientRule(prev, nextRule, {
            source_type: rule.source_type,
            source_value: rule.source_value,
            subject_type: rule.subject_type,
            subject_value: rule.subject_value,
          })
        : prev,
    );
  };

  const updateRule = (
    rule: MCPToolAccessOverride,
    patch: Partial<MCPAccessRule>,
  ) => {
    const nextRule = withRuleDefaults(rule, patch);
    setPolicy((prev) =>
      prev
        ? upsertToolRule(prev, nextRule, {
            tool_name: rule.tool_name,
            source_type: rule.source_type,
            source_value: rule.source_value,
            subject_type: rule.subject_type,
            subject_value: rule.subject_value,
          })
        : prev,
    );
  };

  const handleSave = async () => {
    if (!policy) return;
    const validationError = validateMCPAccessPolicy(policy);
    if (validationError) {
      message.error(t(`mcp.access.validation.${validationError.reason}`));
      return;
    }
    const validationWarning = findMCPAccessPolicyWarning(
      policy,
      principalOptions,
    );
    if (validationWarning) {
      message.warning(t(`mcp.access.validation.${validationWarning.reason}`));
    }
    setSaving(true);
    try {
      const ok = await onSave(policy);
      if (ok) {
        setInitialPolicySignature(policySignature(policy));
        onClose();
      }
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (!isDirty || saving) {
      onClose();
      return;
    }
    Modal.confirm({
      title: t("mcp.access.discardTitle"),
      content: t("mcp.access.discardContent"),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: onClose,
    });
  };

  return (
    <Modal
      title={`${client.name} - ${t("mcp.tools")}`}
      open={open}
      onCancel={handleClose}
      width="min(1040px, calc(100vw - 32px))"
      footer={
        <div style={{ textAlign: "right" }}>
          <Button onClick={handleClose} style={{ marginRight: 8 }}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            onClick={handleSave}
            loading={saving}
            disabled={!policy || loading}
          >
            {t("common.save")}
          </Button>
        </div>
      }
    >
      {loading && !policy ? (
        <div className={styles.toolsLoading}>
          <Spin />
        </div>
      ) : policy ? (
        <div className={styles.accessModalBody}>
          <MCPAccessClientPanel
            policy={policy}
            principalOptions={principalOptions}
            setDefaultEffect={setDefaultEffect}
            addClientAccessRule={() =>
              setPolicy((prev) => (prev ? addClientRule(prev) : prev))
            }
            updateClientRule={updateClientRule}
            setClientRuleEffect={(rule, effect) =>
              setPolicy((prev) =>
                prev ? upsertClientRule(prev, { ...rule, effect }) : prev,
              )
            }
            deleteClientRule={(rule) =>
              setPolicy((prev) => (prev ? removeClientRule(prev, rule) : prev))
            }
            effectLabel={effectLabel}
          />

          {toolsError && <div className={styles.toolsError}>{toolsError}</div>}

          {groups.length === 0 ? (
            <Empty description={t("mcp.noTools")} />
          ) : (
            <MCPAccessToolPanel
              groups={groups}
              principalOptions={principalOptions}
              setToolDefaultEffect={(toolName, effect) =>
                setPolicy((prev) =>
                  prev ? upsertToolDefault(prev, toolName, effect) : prev,
                )
              }
              addRule={(toolName) =>
                setPolicy((prev) => (prev ? addToolRule(prev, toolName) : prev))
              }
              updateRule={updateRule}
              setRuleEffect={(rule, effect) =>
                setPolicy((prev) =>
                  prev ? upsertToolRule(prev, { ...rule, effect }) : prev,
                )
              }
              deleteRule={(rule) =>
                setPolicy((prev) => (prev ? removeToolRule(prev, rule) : prev))
              }
              effectLabel={effectLabel}
            />
          )}
        </div>
      ) : (
        <div className={styles.toolsError}>{t("mcp.access.loadError")}</div>
      )}
    </Modal>
  );
};

function withRuleDefaults<Rule extends MCPAccessRule>(
  rule: Rule,
  patch: Partial<MCPAccessRule>,
): Rule {
  const nextRule = { ...rule, ...patch };
  if (patch.subject_type) {
    nextRule.subject_value = "";
  }
  if (
    (patch.source_type !== undefined || patch.source_value !== undefined) &&
    patch.subject_value === undefined &&
    nextRule.subject_type === "user"
  ) {
    nextRule.subject_value = "";
  }
  return nextRule;
}

function policySignature(policy: MCPAccessPolicy): string {
  return JSON.stringify(normalizeMCPAccessPolicy(policy));
}
