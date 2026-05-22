import type { MCPClientInfo } from "../../../../api/types";
import {
  getMcpTemplateById,
  type MCPMarketTemplate,
} from "./mcpTemplates";

export interface MCPMarketClientMeta {
  fromMarket: boolean;
  templateId: string | null;
  userNote: string;
}

function isHttpTransport(transport: string): boolean {
  return transport === "streamable_http" || transport === "sse";
}

function argsSignature(client: MCPClientInfo): string {
  return (client.args ?? []).join(" ");
}

/** Infer market template from installed client shape (package / transport). */
export function inferMarketTemplateId(client: MCPClientInfo): string | null {
  const args = argsSignature(client);
  if (args.includes("@liangshanli/mcp-server-mysql")) return "mysql";
  if (args.includes("aliyun-sls-mcp")) return "aliyun-sls";
  if (
    args.includes("host-mcp-jenkins") ||
    args.includes("jenkins-mcp") ||
    args.includes("@vijaynkw/jenkins-mcp") ||
    args.includes("@mister-good-deal/host-mcp-jenkins")
  ) {
    return "jenkins";
  }
  if (
    client.key === "gitee" &&
    isHttpTransport(client.transport) &&
    (client.url ?? "").includes("gitee.com")
  ) {
    return "gitee";
  }
  const tpl = getMcpTemplateById(client.key);
  if (tpl && clientMatchesTemplate(client, tpl)) {
    return tpl.id;
  }
  return null;
}

export function clientMatchesTemplate(
  client: MCPClientInfo,
  template: MCPMarketTemplate,
): boolean {
  if (client.transport !== template.transport) {
    return false;
  }
  if (isHttpTransport(template.transport)) {
    return true;
  }
  const args = argsSignature(client);
  const marker = (template.args ?? []).find(
    (a) => a.startsWith("@") || (!a.startsWith("-") && a.includes("mcp")),
  );
  if (marker && !args.includes(marker)) {
    return false;
  }
  return true;
}

export function resolveMarketTemplate(
  client: MCPClientInfo,
): MCPMarketTemplate | undefined {
  const meta = parseMarketClientMeta(client);
  if (meta.templateId) {
    const tpl = getMcpTemplateById(meta.templateId);
    if (tpl && clientMatchesTemplate(client, tpl)) {
      return tpl;
    }
  }
  const inferred = inferMarketTemplateId(client);
  if (inferred) {
    return getMcpTemplateById(inferred);
  }
  return undefined;
}

/** Persist market origin in description (no backend schema change). */
export function formatMarketDescription(
  templateId: string,
  userNote?: string,
): string {
  const note = userNote?.trim();
  return note ? `[market:${templateId}]\n${note}` : `[market:${templateId}]`;
}

export function parseMarketClientMeta(client: MCPClientInfo): MCPMarketClientMeta {
  const raw = (client.description ?? "").trim();

  const tagged = raw.match(/^\[market:([^\]]+)\](?:\n([\s\S]*))?$/);
  if (tagged) {
    return {
      fromMarket: true,
      templateId: tagged[1].trim(),
      userNote: (tagged[2] ?? "").trim(),
    };
  }

  const legacy = raw.match(/^\[market\]\s*(\S+)/);
  if (legacy) {
    return {
      fromMarket: true,
      templateId: legacy[1].trim(),
      userNote: "",
    };
  }

  const inferred = inferMarketTemplateId(client);
  if (inferred) {
    return {
      fromMarket: true,
      templateId: inferred,
      userNote: raw.startsWith("[market") ? "" : raw,
    };
  }

  return { fromMarket: false, templateId: null, userNote: raw };
}

export function hasStaticBearerAuth(client: MCPClientInfo): boolean {
  const auth =
    client.headers?.Authorization ?? client.headers?.authorization ?? "";
  return /^bearer\s+\S/i.test(auth.trim());
}

export function resolveClientDisplayName(
  client: MCPClientInfo,
  meta: MCPMarketClientMeta,
  t: (key: string) => string,
): string {
  if (meta.templateId) {
    const tpl = getMcpTemplateById(meta.templateId);
    if (tpl) {
      if (!client.name?.trim() || client.name.trim() === client.key) {
        return t(tpl.nameKey);
      }
    }
  }
  return client.name?.trim() || client.key;
}

export function resolveClientDisplayDescription(
  client: MCPClientInfo,
  meta: MCPMarketClientMeta,
  t: (key: string) => string,
): string {
  if (meta.userNote) return meta.userNote;
  if (meta.templateId) {
    const tpl = getMcpTemplateById(meta.templateId);
    if (tpl) return t(tpl.descriptionKey);
  }
  return client.description?.trim() || "";
}
