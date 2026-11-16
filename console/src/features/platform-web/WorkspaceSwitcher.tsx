import { useRef, useState } from "react";
import { Button, Dropdown } from "antd";
import { SharedModal } from "../../components/interaction/SharedModal";
import {
  ChevronDown,
  Cloud,
  Download,
  LogOut,
  Monitor,
  FlaskConical,
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

export function WorkspaceSwitcher() {
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
  const items = (["cloud", "bound"] as const).map((kind) => ({
    type: "group" as const,
    key: kind,
    label: t(kind === "cloud" ? "webApp.cloud" : "webApp.bound"),
    children: targets
      .filter((item) => item.kind === kind)
      .map((item) => ({
        key: targetKey(item),
        icon: kind === "cloud" ? <Cloud size={16} /> : <Monitor size={16} />,
        label: `${item.name}${
          item.online ? "" : ` · ${t("platformAccess.offline")}`
        }`,
        onClick: () => action(() => choose(item)),
      })),
  }));
  return (
    <>
      <Dropdown
        autoFocus
        trigger={["click"]}
        menu={{
          selectedKeys: target ? [targetKey(target)] : [],
          items: [
            ...items,
            { type: "divider" },
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
          className={styles.workspace}
          aria-label={`${t("webApp.switchTarget")}: ${
            target?.name ?? ""
          } (Beta)`}
          title={`${target?.name ?? t("webApp.switchTarget")} · Beta`}
          icon={<FlaskConical size={16} />}
        >
          <span className={styles.workspaceName}>
            {target?.name ?? t("webApp.switchTarget")}
          </span>
          <ChevronDown size={15} className={styles.workspaceChevron} />
        </Button>
      </Dropdown>
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
