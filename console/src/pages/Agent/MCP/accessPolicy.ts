import type {
  MCPAccessEffect,
  MCPAccessPolicy,
  MCPAccessPrincipalOption,
  MCPAccessRule,
  MCPAccessSourceType,
  MCPAccessSubjectType,
  MCPToolDefaultPolicy,
  MCPToolAccessOverride,
  MCPToolInfo,
} from "../../../api/types";

export interface MCPAccessToolGroup {
  toolName: string;
  description: string;
  inputSchema: Record<string, unknown>;
  stale: boolean;
  defaultEffect: MCPAccessEffect;
  hasExplicitDefault: boolean;
  rules: MCPToolAccessOverride[];
}

type RuleIdentity = Pick<
  MCPAccessRule,
  "source_type" | "source_value" | "subject_type" | "subject_value"
>;

type ToolRuleIdentity = RuleIdentity & Pick<MCPToolAccessOverride, "tool_name">;

const DEFAULT_ACCESS_SOURCE_TYPE: MCPAccessSourceType = "channel";
const DEFAULT_CHANNEL_SOURCE = "console";

export interface MCPAccessPolicyValidationError {
  reason: "missingUserValue" | "ambiguousUserSource";
  rule: MCPAccessRule | MCPToolAccessOverride;
}

export interface MCPAccessPolicyValidationWarning {
  reason: "unknownUserValue";
  rule: MCPAccessRule | MCPToolAccessOverride;
}

export interface MCPSubjectValueOption {
  label: string;
  value: string;
}

export const MCP_CHANNEL_SOURCE_VALUES = [
  "console",
  "dingtalk",
  "feishu",
  "wechat",
  "wecom",
  "discord",
  "telegram",
  "qq",
  "imessage",
  "mattermost",
  "matrix",
  "onebot",
  "mqtt",
  "voice",
  "sip",
  "xiaoyi",
] as const;

export function normalizeMCPAccessPolicy(
  policy: MCPAccessPolicy,
): MCPAccessPolicy {
  return {
    default_effect: policy.default_effect || "deny",
    client_overrides: sortAccessRules(policy.client_overrides || []),
    tool_defaults: sortToolDefaults(policy.tool_defaults || []),
    tool_overrides: sortToolRules(policy.tool_overrides || []),
    unmanaged_rules_count: policy.unmanaged_rules_count || 0,
  };
}

export function normalizeMCPAccessRule(rule: MCPAccessRule): MCPAccessRule {
  const sourceType = normalizeSourceType(rule.source_type);
  const subjectType = normalizeSubjectType(rule.subject_type);
  return {
    source_type: sourceType,
    source_value: normalizeSourceValue(rule.source_value),
    subject_type: subjectType,
    subject_value:
      subjectType === "all" ? "" : (rule.subject_value || "").trim(),
    effect: rule.effect,
  };
}

export function normalizeMCPToolRule(
  rule: MCPToolAccessOverride,
): MCPToolAccessOverride {
  return {
    tool_name: rule.tool_name || "*",
    ...normalizeMCPAccessRule(rule),
  };
}

export function normalizeMCPToolDefault(
  defaultPolicy: MCPToolDefaultPolicy,
): MCPToolDefaultPolicy {
  return {
    tool_name: defaultPolicy.tool_name || "*",
    effect: defaultPolicy.effect,
  };
}

export function buildMCPAccessToolGroups(
  tools: MCPToolInfo[],
  policy: MCPAccessPolicy,
): MCPAccessToolGroup[] {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const rulesByTool = new Map<string, MCPToolAccessOverride[]>();
  normalizedPolicy.tool_overrides.forEach((override) => {
    const rule = normalizeMCPToolRule(override);
    const rules = rulesByTool.get(rule.tool_name) || [];
    rules.push(rule);
    rulesByTool.set(rule.tool_name, rules);
  });
  const defaultsByTool = new Map(
    normalizedPolicy.tool_defaults.map((item) => [
      item.tool_name,
      normalizeMCPToolDefault(item),
    ]),
  );

  const currentToolNames = new Set(tools.map((tool) => tool.name));
  const currentGroups: MCPAccessToolGroup[] = tools.map((tool) => ({
    toolName: tool.name,
    description: tool.description,
    inputSchema: tool.input_schema,
    stale: false,
    defaultEffect:
      defaultsByTool.get(tool.name)?.effect || normalizedPolicy.default_effect,
    hasExplicitDefault: defaultsByTool.has(tool.name),
    rules: sortToolRules(rulesByTool.get(tool.name) || []),
  }));

  const staleToolNames = new Set([
    ...Array.from(rulesByTool.keys()),
    ...Array.from(defaultsByTool.keys()),
  ]);
  const staleGroups: MCPAccessToolGroup[] = Array.from(staleToolNames)
    .filter((toolName) => toolName !== "*" && !currentToolNames.has(toolName))
    .map((toolName) => ({
      toolName,
      description: "",
      inputSchema: {},
      stale: true,
      defaultEffect:
        defaultsByTool.get(toolName)?.effect || normalizedPolicy.default_effect,
      hasExplicitDefault: defaultsByTool.has(toolName),
      rules: sortToolRules(rulesByTool.get(toolName) || []),
    }));

  return [...currentGroups, ...staleGroups];
}

export function addClientRule(policy: MCPAccessPolicy): MCPAccessPolicy {
  return upsertClientRule(policy, {
    source_type: "channel",
    source_value: nextDefaultSourceValue(policy, null),
    subject_type: "all",
    subject_value: "",
    effect: "ask",
  });
}

export function addToolRule(
  policy: MCPAccessPolicy,
  toolName: string,
): MCPAccessPolicy {
  return upsertToolRule(policy, {
    tool_name: toolName,
    source_type: "channel",
    source_value: nextDefaultSourceValue(policy, toolName),
    subject_type: "all",
    subject_value: "",
    effect: "ask",
  });
}

export function upsertClientRule(
  policy: MCPAccessPolicy,
  rule: MCPAccessRule,
  previousRule?: RuleIdentity,
): MCPAccessPolicy {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const nextRule = normalizeMCPAccessRule(rule);
  const previousKey = previousRule
    ? accessRuleIdentityKey(previousRule)
    : accessRuleIdentityKey(nextRule);
  const nextKey = accessRuleIdentityKey(nextRule);
  const nextOverrides = normalizedPolicy.client_overrides.filter((item) => {
    const itemKey = accessRuleIdentityKey(normalizeMCPAccessRule(item));
    return itemKey !== previousKey && itemKey !== nextKey;
  });
  nextOverrides.push(nextRule);
  return {
    ...normalizedPolicy,
    client_overrides: sortAccessRules(nextOverrides),
  };
}

export function upsertToolRule(
  policy: MCPAccessPolicy,
  rule: MCPToolAccessOverride,
  previousRule?: ToolRuleIdentity,
): MCPAccessPolicy {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const nextRule = normalizeMCPToolRule(rule);
  const previousKey = previousRule
    ? toolRuleIdentityKey(previousRule)
    : toolRuleIdentityKey(nextRule);
  const nextKey = toolRuleIdentityKey(nextRule);
  const nextOverrides = normalizedPolicy.tool_overrides.filter((item) => {
    const itemKey = toolRuleIdentityKey(normalizeMCPToolRule(item));
    return itemKey !== previousKey && itemKey !== nextKey;
  });
  nextOverrides.push(nextRule);
  return {
    ...normalizedPolicy,
    tool_overrides: sortToolRules(nextOverrides),
  };
}

export function upsertToolDefault(
  policy: MCPAccessPolicy,
  toolName: string,
  effect: MCPAccessEffect,
): MCPAccessPolicy {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const nextDefaults = normalizedPolicy.tool_defaults.filter(
    (item) => item.tool_name !== toolName,
  );
  nextDefaults.push({ tool_name: toolName, effect });
  return {
    ...normalizedPolicy,
    tool_defaults: sortToolDefaults(nextDefaults),
  };
}

export function removeClientRule(
  policy: MCPAccessPolicy,
  rule: RuleIdentity,
): MCPAccessPolicy {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const targetKey = accessRuleIdentityKey(rule);
  return {
    ...normalizedPolicy,
    client_overrides: normalizedPolicy.client_overrides.filter(
      (item) =>
        accessRuleIdentityKey(normalizeMCPAccessRule(item)) !== targetKey,
    ),
  };
}

export function removeToolRule(
  policy: MCPAccessPolicy,
  rule: ToolRuleIdentity,
): MCPAccessPolicy {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const targetKey = toolRuleIdentityKey(rule);
  return {
    ...normalizedPolicy,
    tool_overrides: normalizedPolicy.tool_overrides.filter(
      (item) => toolRuleIdentityKey(normalizeMCPToolRule(item)) !== targetKey,
    ),
  };
}

export function applyPrincipalOptionToRule(
  principal: MCPAccessPrincipalOption,
): Pick<
  MCPAccessRule,
  "source_type" | "source_value" | "subject_type" | "subject_value"
> {
  return {
    source_type: principal.source_type,
    source_value: principal.source_value,
    subject_type: principal.subject_type,
    subject_value: principal.subject_value,
  };
}

export function filterPrincipalOptionsForRule(
  principals: MCPAccessPrincipalOption[],
  rule: MCPAccessRule,
): MCPAccessPrincipalOption[] {
  const sourceType = normalizeSourceType(rule.source_type);
  const sourceValue = normalizeSourceValue(rule.source_value);
  if (isWildcardSourceValue(sourceValue)) {
    return [];
  }

  const bySubjectValue = new Map<string, MCPAccessPrincipalOption>();
  principals.forEach((principal) => {
    if (
      normalizeSourceType(principal.source_type) !== sourceType ||
      normalizeSourceValue(principal.source_value) !== sourceValue
    ) {
      return;
    }
    const subjectValue = (principal.subject_value || "").trim();
    if (!subjectValue || bySubjectValue.has(subjectValue)) {
      return;
    }
    bySubjectValue.set(subjectValue, principal);
  });
  return Array.from(bySubjectValue.values());
}

export function buildSubjectValueOptions(
  principals: MCPAccessPrincipalOption[],
  rule: MCPAccessRule,
): MCPSubjectValueOption[] {
  return filterPrincipalOptionsForRule(principals, rule).map((principal) => ({
    label: principal.subject_value,
    value: principal.subject_value,
  }));
}

export function ruleHasAmbiguousUserSource(rule: MCPAccessRule): boolean {
  return (
    normalizeSourceType(rule.source_type) === "channel" &&
    isWildcardSourceValue(rule.source_value) &&
    normalizeSubjectType(rule.subject_type) === "user" &&
    Boolean((rule.subject_value || "").trim())
  );
}

export function ruleHasUnknownUserValue(
  principals: MCPAccessPrincipalOption[],
  rule: MCPAccessRule,
): boolean {
  const normalized = normalizeMCPAccessRule(rule);
  return (
    normalized.subject_type === "user" &&
    Boolean(normalized.subject_value) &&
    normalized.subject_value !== "*" &&
    principalOptionsCoverSourceType(principals, normalized.source_type) &&
    !ruleHasAmbiguousUserSource(normalized) &&
    !filterPrincipalOptionsForRule(principals, normalized).some(
      (principal) => principal.subject_value === normalized.subject_value,
    )
  );
}

export function sourceScopedSubjectPlaceholder(rule: MCPAccessRule): string {
  const sourceValue = normalizeSourceValue(rule.source_value);
  if (
    normalizeSourceType(rule.source_type) !== "channel" ||
    isWildcardSourceValue(sourceValue)
  ) {
    return "user ID in selected source";
  }
  return `${sourceValue} user ID`;
}

export function validateMCPAccessPolicy(
  policy: MCPAccessPolicy,
): MCPAccessPolicyValidationError | null {
  const rules: Array<MCPAccessRule | MCPToolAccessOverride> = [
    ...(policy.client_overrides || []),
    ...(policy.tool_overrides || []),
  ];
  for (const rule of rules) {
    const normalized = normalizeMCPAccessRule(rule);
    if (normalized.subject_type !== "user") {
      continue;
    }
    if (
      !normalized.subject_value ||
      normalized.subject_value === "*" ||
      !normalized.source_value
    ) {
      return { reason: "missingUserValue", rule };
    }
    if (ruleHasAmbiguousUserSource(normalized)) {
      return { reason: "ambiguousUserSource", rule };
    }
  }
  return null;
}

export function findMCPAccessPolicyWarning(
  policy: MCPAccessPolicy,
  principals: MCPAccessPrincipalOption[] = [],
): MCPAccessPolicyValidationWarning | null {
  const rules: Array<MCPAccessRule | MCPToolAccessOverride> = [
    ...(policy.client_overrides || []),
    ...(policy.tool_overrides || []),
  ];
  for (const rule of rules) {
    if (ruleHasUnknownUserValue(principals, rule)) {
      return { reason: "unknownUserValue", rule };
    }
  }
  return null;
}

function principalOptionsCoverSourceType(
  principals: MCPAccessPrincipalOption[],
  sourceType: MCPAccessSourceType,
): boolean {
  return (
    sourceType === DEFAULT_ACCESS_SOURCE_TYPE ||
    principals.some(
      (principal) => normalizeSourceType(principal.source_type) === sourceType,
    )
  );
}

export function accessRuleIdentityKey(rule: RuleIdentity): string {
  const normalized = normalizeAccessRuleIdentity(rule);
  return [
    normalized.source_type,
    normalized.source_value,
    normalized.subject_type,
    normalized.subject_value,
  ].join("\u0000");
}

export function toolRuleIdentityKey(rule: ToolRuleIdentity): string {
  const normalized = normalizeToolRuleIdentity(rule);
  return [
    normalized.tool_name,
    normalized.source_type,
    normalized.source_value,
    normalized.subject_type,
    normalized.subject_value,
  ].join("\u0000");
}

function normalizeAccessRuleIdentity(rule: RuleIdentity): RuleIdentity {
  const sourceType = normalizeSourceType(rule.source_type);
  const subjectType = normalizeSubjectType(rule.subject_type);
  return {
    source_type: sourceType,
    source_value: normalizeSourceValue(rule.source_value),
    subject_type: subjectType,
    subject_value:
      subjectType === "all" ? "" : (rule.subject_value || "").trim(),
  };
}

function normalizeToolRuleIdentity(rule: ToolRuleIdentity): ToolRuleIdentity {
  return {
    tool_name: rule.tool_name || "*",
    ...normalizeAccessRuleIdentity(rule),
  };
}

function nextDefaultSourceValue(
  policy: MCPAccessPolicy,
  toolName: string | null,
): string {
  const normalizedPolicy = normalizeMCPAccessPolicy(policy);
  const used = new Set(
    toolName === null
      ? normalizedPolicy.client_overrides.map((item) =>
          accessRuleIdentityKey(normalizeMCPAccessRule(item)),
        )
      : normalizedPolicy.tool_overrides
          .filter((item) => item.tool_name === toolName)
          .map((item) => toolRuleIdentityKey(normalizeMCPToolRule(item))),
  );
  for (const sourceValue of MCP_CHANNEL_SOURCE_VALUES) {
    const candidateBase = {
      source_type: "channel",
      source_value: sourceValue,
      subject_type: "all",
      subject_value: "",
    } as const;
    const candidate =
      toolName === null
        ? accessRuleIdentityKey(candidateBase)
        : toolRuleIdentityKey({ tool_name: toolName, ...candidateBase });
    if (!used.has(candidate)) return sourceValue;
  }
  return DEFAULT_CHANNEL_SOURCE;
}

function normalizeSourceValue(sourceValue: string): string {
  const trimmed = (sourceValue || "").trim();
  return trimmed;
}

function isWildcardSourceValue(sourceValue: string): boolean {
  const normalized = normalizeSourceValue(sourceValue);
  return normalized === "" || normalized === "*";
}

function normalizeSourceType(
  sourceType: MCPAccessSourceType | string,
): MCPAccessSourceType {
  const trimmed = (sourceType || "").trim();
  return trimmed || "channel";
}

function normalizeSubjectType(
  subjectType: MCPAccessSubjectType,
): MCPAccessSubjectType {
  return subjectType === "user" ? "user" : "all";
}

function sortToolRules(
  rules: MCPToolAccessOverride[],
): MCPToolAccessOverride[] {
  return [...rules].map(normalizeMCPToolRule).sort((a, b) => {
    const sourceOrder =
      a.source_type.localeCompare(b.source_type) ||
      a.source_value.localeCompare(b.source_value);
    const subjectOrder =
      a.subject_type.localeCompare(b.subject_type) ||
      a.subject_value.localeCompare(b.subject_value);
    return (
      a.tool_name.localeCompare(b.tool_name) || sourceOrder || subjectOrder
    );
  });
}

function sortAccessRules(rules: MCPAccessRule[]): MCPAccessRule[] {
  return [...rules].map(normalizeMCPAccessRule).sort((a, b) => {
    const sourceOrder =
      a.source_type.localeCompare(b.source_type) ||
      a.source_value.localeCompare(b.source_value);
    const subjectOrder =
      a.subject_type.localeCompare(b.subject_type) ||
      a.subject_value.localeCompare(b.subject_value);
    return sourceOrder || subjectOrder;
  });
}

function sortToolDefaults(
  defaults: MCPToolDefaultPolicy[],
): MCPToolDefaultPolicy[] {
  return [...defaults]
    .map(normalizeMCPToolDefault)
    .sort((a, b) => a.tool_name.localeCompare(b.tool_name));
}
