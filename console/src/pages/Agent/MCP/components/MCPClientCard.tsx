import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { MCPClientInfo, MCPToolInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useState, useCallback } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  Eye,
  EyeOff,
  Wrench,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  KeyRound,
  Loader2,
} from "lucide-react";
import api from "../../../../api";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { MCPOAuthSection } from "./MCPOAuthSection";
import styles from "../index.module.less";

interface MCPClientUpdate {
  name?: string;
  description?: string;
  command?: string;
  enabled?: boolean;
  transport?: "stdio" | "streamable_http" | "sse";
  url?: string;
  headers?: Record<string, string>;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: MCPClientUpdate) => Promise<boolean>;
  onRefresh?: () => Promise<void>;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onRefresh,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [toolsModalOpen, setToolsModalOpen] = useState(false);
  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [toolsSaving, setToolsSaving] = useState(false);
  const [toolToggles, setToolToggles] = useState<Record<string, boolean>>({});
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [oauthModalOpen, setOauthModalOpen] = useState(false);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthScope, setOauthScope] = useState(
    client.oauth_status?.scope || "",
  );
  const [oauthAuthEndpoint, setOauthAuthEndpoint] = useState("");
  const [oauthTokenEndpoint, setOauthTokenEndpoint] = useState("");

  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

  const oauthStatus = client.oauth_status;
  const now = Date.now() / 1000;
  const isOauthAuthorized =
    !!oauthStatus?.authorized && oauthStatus.expires_at > now;
  const isOauthExpired =
    !!oauthStatus?.authorized && oauthStatus.expires_at <= now;
  const hasOauth = !!oauthStatus;

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(client, e);
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete(client, null as unknown as React.MouseEvent);
  };

  const handleCardClick = () => {
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      const { key: _key, ...updates } = parsed;
      const success = await onUpdate(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch {
      alert("Invalid JSON format");
    }
  };

  const handleShowTools = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setToolsModalOpen(true);
      setToolsLoading(true);
      setToolsError(null);
      setTools([]);
      setToolToggles({});
      try {
        const data = await api.listMCPTools(client.key);
        setTools(data);
        const toggles: Record<string, boolean> = {};
        data.forEach((tool) => {
          toggles[tool.name] = tool.enabled;
        });
        setToolToggles(toggles);
      } catch (err: any) {
        const msg = err?.message || "";
        if (msg.includes("connecting") || msg.includes("not ready")) {
          setToolsError(t("mcp.toolsConnecting"));
        } else {
          setToolsError(msg || t("mcp.toolsLoadError"));
        }
      } finally {
        setToolsLoading(false);
      }
    },
    [client.key, t],
  );

  const handleToolToggle = useCallback((toolName: string, checked: boolean) => {
    setToolToggles((prev) => ({ ...prev, [toolName]: checked }));
  }, []);

  const handleSaveToolWhitelist = useCallback(async () => {
    setToolsSaving(true);
    try {
      const allEnabled = Object.values(toolToggles).every((v) => v);
      const enabledTools = allEnabled
        ? null
        : Object.entries(toolToggles)
            .filter(([, enabled]) => enabled)
            .map(([name]) => name);
      const data = await api.updateMCPToolWhitelist(client.key, enabledTools);
      setTools(data);
      const toggles: Record<string, boolean> = {};
      data.forEach((tool) => {
        toggles[tool.name] = tool.enabled;
      });
      setToolToggles(toggles);
      onRefresh?.();
    } catch (err: any) {
      message.error(
        err?.message || t("mcp.toolsSaveError", "Failed to save tool settings"),
      );
    } finally {
      setToolsSaving(false);
    }
  }, [client.key, toolToggles, onRefresh, message, t]);

  const clientJson = JSON.stringify(client, null, 2);

  return (
    <>
      <Card
        onClick={handleCardClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal} cursor-pointer`}
      >
        <CardContent className="p-0">
          <div className={styles.cardHeader}>
            <div className="flex items-center gap-1.5 min-w-0">
              <h3 className={styles.mcpTitle} title={client.name}>
                {client.name}
              </h3>
              <span
                className={`${styles.typeBadge} ${
                  isRemote ? styles.remote : styles.local
                }`}
              >
                {clientType}
              </span>
              {hasOauth && isOauthExpired && (
                <span title={t("mcp.oauth.expired")}>
                  <ShieldAlert size={13} className="text-orange-500 shrink-0" />
                </span>
              )}
              {hasOauth && isOauthAuthorized && (
                <span title={t("mcp.oauth.authorized")}>
                  <ShieldCheck size={13} className="text-green-600 shrink-0" />
                </span>
              )}
              {hasOauth && !isOauthAuthorized && !isOauthExpired && (
                <span title={t("mcp.oauth.notAuthorized")}>
                  <ShieldX
                    size={13}
                    className="text-muted-foreground shrink-0"
                  />
                </span>
              )}
            </div>
            <div className={styles.statusContainer}>
              <span className={styles.statusDot} />
              <span className={styles.statusText}>
                {client.enabled ? t("common.enabled") : t("common.disabled")}
              </span>
            </div>
          </div>

          <p className={styles.mcpDescription}>{client.description || "-"}</p>

          <div className={styles.cardFooter}>
            <Button
              variant="outline"
              size="sm"
              className={styles.toolsButton}
              onClick={handleShowTools}
              disabled={!client.enabled || toolsLoading}
            >
              {toolsLoading ? (
                <Loader2 size={14} className="animate-spin mr-1" />
              ) : (
                <Wrench size={14} className="mr-1" />
              )}
              {t("mcp.tools")}
            </Button>
            {isRemote && (
              <Button
                variant="outline"
                size="sm"
                className={styles.toggleButton}
                onClick={(e) => {
                  e.stopPropagation();
                  setOauthModalOpen(true);
                }}
                style={
                  isOauthAuthorized
                    ? {
                        color: "#27ae60",
                        borderColor: "#27ae60",
                        background: "rgba(39,174,96,0.06)",
                      }
                    : isOauthExpired
                    ? {
                        color: "#e67e22",
                        borderColor: "#e67e22",
                        background: "rgba(230,126,34,0.06)",
                      }
                    : undefined
                }
              >
                {isOauthAuthorized ? (
                  <ShieldCheck size={13} className="mr-1" />
                ) : isOauthExpired ? (
                  <ShieldAlert size={13} className="mr-1" />
                ) : (
                  <KeyRound size={13} className="mr-1" />
                )}
                {isOauthAuthorized
                  ? t("mcp.oauth.authorized")
                  : isOauthExpired
                  ? t("mcp.oauth.expired")
                  : t("mcp.oauth.authorize")}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className={styles.toggleButton}
              onClick={(e) => {
                e.stopPropagation();
                handleToggleClick(e);
              }}
            >
              {client.enabled ? (
                <EyeOff size={14} className="mr-1" />
              ) : (
                <Eye size={14} className="mr-1" />
              )}
              {client.enabled ? t("common.disable") : t("common.enable")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              className={styles.deleteButton}
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteClick(e);
              }}
            >
              {t("common.delete")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={deleteModalOpen} onOpenChange={setDeleteModalOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("common.confirm")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("mcp.deleteConfirm")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmDelete}
            >
              {t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={toolsModalOpen} onOpenChange={setToolsModalOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{`${client.name} - ${t("mcp.tools")}`}</DialogTitle>
          </DialogHeader>
          {toolsLoading ? (
            <div className={styles.toolsLoading}>
              <Loader2 className="animate-spin" />
            </div>
          ) : toolsError ? (
            <div className={styles.toolsError}>{toolsError}</div>
          ) : tools.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("mcp.noTools")}</p>
          ) : (
            <div className={styles.toolsList}>
              {tools.map((tool) => (
                <div key={tool.name} className={styles.toolItem}>
                  <div className={styles.toolHeader}>
                    <Switch
                      checked={toolToggles[tool.name] ?? tool.enabled}
                      onCheckedChange={(checked) =>
                        handleToolToggle(tool.name, checked)
                      }
                    />
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full border ${
                        toolToggles[tool.name] ?? tool.enabled
                          ? "border-blue-300 bg-blue-50 text-blue-700"
                          : "border-muted bg-muted text-muted-foreground"
                      }`}
                    >
                      {tool.name}
                    </span>
                  </div>
                  {tool.description && (
                    <p className={styles.toolDescription}>{tool.description}</p>
                  )}
                  {tool.input_schema &&
                    Object.keys(tool.input_schema).length > 0 && (
                      <details className={styles.toolSchema}>
                        <summary>{t("mcp.toolSchema")}</summary>
                        <pre className={styles.toolSchemaContent}>
                          {JSON.stringify(tool.input_schema, null, 2)}
                        </pre>
                      </details>
                    )}
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setToolsModalOpen(false)}>
              {t("common.close")}
            </Button>
            {tools.length > 0 && (
              <Button onClick={handleSaveToolWhitelist} disabled={toolsSaving}>
                {toolsSaving && (
                  <Loader2 size={14} className="animate-spin mr-1" />
                )}
                {t("common.save")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={jsonModalOpen} onOpenChange={setJsonModalOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{`${client.name} - Configuration`}</DialogTitle>
          </DialogHeader>
          <div className={styles.maskedFieldHint}>
            {t("mcp.maskedFieldHint")}
          </div>
          {isEditing ? (
            <Textarea
              value={editedJson}
              onChange={(e) => setEditedJson(e.target.value)}
              rows={15}
              style={{
                fontFamily: "Monaco, Courier New, monospace",
                fontSize: 13,
              }}
            />
          ) : (
            <pre
              style={{
                backgroundColor: isDark ? "#1f1f1f" : "#f5f5f5",
                color: isDark ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.88)",
                padding: 16,
                borderRadius: 8,
                maxHeight: 400,
                overflow: "auto",
              }}
            >
              {clientJson}
            </pre>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setJsonModalOpen(false)}>
              {t("common.cancel")}
            </Button>
            {isEditing ? (
              <Button onClick={handleSaveJson}>{t("common.save")}</Button>
            ) : (
              <Button onClick={() => setIsEditing(true)}>
                {t("common.edit")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={oauthModalOpen} onOpenChange={setOauthModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              <span className="flex items-center gap-2">
                {isOauthAuthorized ? (
                  <ShieldCheck size={16} className="text-green-600" />
                ) : isOauthExpired ? (
                  <ShieldAlert size={16} className="text-orange-500" />
                ) : (
                  <ShieldX size={16} className="text-muted-foreground" />
                )}
                {`${client.name} — ${t("mcp.oauth.manage")}`}
              </span>
            </DialogTitle>
          </DialogHeader>
          <MCPOAuthSection
            url={client.url}
            clientKey={client.key}
            oauthEnabled
            currentOAuthStatus={oauthStatus}
            clientId={oauthClientId}
            scope={oauthScope}
            authEndpoint={oauthAuthEndpoint}
            tokenEndpoint={oauthTokenEndpoint}
            onClientIdChange={setOauthClientId}
            onScopeChange={setOauthScope}
            onAuthEndpointChange={setOauthAuthEndpoint}
            onTokenEndpointChange={setOauthTokenEndpoint}
            onAuthChanged={() => {
              onRefresh?.();
            }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setOauthModalOpen(false)}>
              {t("common.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
});
