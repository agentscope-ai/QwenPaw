import { useRef, useState } from "react";
import { Button, Dropdown } from "antd";
import { SharedModal } from "../../components/interaction/SharedModal";
import {
  ChevronDown,
  Cloud,
  Download,
  LogOut,
  Monitor,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  targetKey,
  useWebWorkspace,
  webRequest,
  type WebTarget,
} from "./client";
import styles from "./platformWeb.module.less";

export function WorkspaceSwitcher({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { target, targets, update } = useWebWorkspace();
  const switching = useRef(false);
  const [error, setError] = useState("");
  const choose = async (next: WebTarget) => {
    if (switching.current) return;
    switching.current = true;
    try {
      await webRequest("/session/target", { kind: next.kind, id: next.id });
    } catch (error) {
      switching.current = false;
      throw error;
    }
  };
  const action = (run: () => Promise<unknown>) => {
    void run().catch((error) => setError(String(error)));
  };
  const items = (["cloud", "bound"] as const).map((kind) => {
    const nodes = targets.filter((item) => item.kind === kind);
    return {
      type: "group" as const,
      key: kind,
      label: t(kind === "cloud" ? "webApp.cloud" : "webApp.bound"),
      children: nodes.length
        ? nodes.map((item) => ({
            key: targetKey(item),
            icon:
              kind === "cloud" ? <Cloud size={16} /> : <Monitor size={16} />,
            label: `${item.name} · ${t(
              item.online ? "platformAccess.online" : "platformAccess.offline",
            )}`,
            onClick: () => action(() => choose(item)),
          }))
        : [
            {
              key: `empty:${kind}`,
              label: t(kind === "cloud" ? "webApp.noCloud" : "webApp.noBound"),
              disabled: true,
            },
          ],
    };
  });
  return (
    <>
      <Dropdown
        autoFocus
        trigger={["click"]}
        menu={{
          className: styles.workspaceMenu,
          selectedKeys: target ? [targetKey(target)] : [],
          items: [
            ...items,
            { type: "divider" },
            {
              key: "refresh",
              icon: <RefreshCw size={16} />,
              label: t("webApp.refresh"),
              onClick: () => action(() => webRequest("/host/reload", {})),
            },
            {
              key: "install",
              icon: <Download size={16} />,
              label: t("webApp.addToHome"),
              onClick: () => action(() => webRequest("/host/install", {})),
            },
            ...(update
              ? [
                  {
                    key: "update",
                    icon: <RefreshCw size={16} />,
                    label: t("webApp.update"),
                    onClick: update,
                  },
                ]
              : []),
            {
              key: "logout",
              icon: <LogOut size={16} />,
              label: t("webApp.signOut"),
              onClick: () =>
                action(async () => {
                  await webRequest("/session/logout", {});
                }),
            },
          ],
        }}
        onOpenChange={(open) => {
          if (open)
            action(async () => {
              useWebWorkspace.setState({
                targets: await webRequest<WebTarget[]>("/targets"),
              });
            });
        }}
      >
        <Button
          type="text"
          className={`${styles.workspace} ${
            className ? styles.menuWorkspace : ""
          } ${className ?? ""}`}
          aria-label={
            target
              ? `${t("webApp.switchTarget")}: ${target.name}`
              : t("webApp.switchTarget")
          }
          title={target?.name ?? t("webApp.switchTarget")}
          icon={
            target?.kind === "cloud" ? (
              <Cloud size={18} />
            ) : (
              <Monitor size={18} />
            )
          }
        >
          <span className={styles.workspaceName}>
            {target?.name ?? t("webApp.switchTarget")}
          </span>
          <ChevronDown size={15} />
        </Button>
      </Dropdown>
      {!className && (
        <Button
          type="text"
          className={styles.refresh}
          icon={<RefreshCw size={18} />}
          aria-label={t("webApp.refresh")}
          title={t("webApp.refresh")}
          onClick={() => action(() => webRequest("/host/reload", {}))}
        />
      )}
      <SharedModal
        open={!!error}
        onCancel={() => setError("")}
        title={t("webApp.switchTarget")}
        footer={null}
      >
        <p>{error}</p>
      </SharedModal>
    </>
  );
}
