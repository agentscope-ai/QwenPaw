import { useState, type ReactNode } from "react";
import { Button, Drawer, Grid } from "antd";
import { useTranslation } from "react-i18next";
import {
  Activity,
  ChevronRight,
  House,
  LogOut,
  Menu,
  Moon,
  RefreshCw,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react";
import LanguageSwitcher from "../../../components/LanguageSwitcher";
import type { Section } from "../pageUtils";
import styles from "./HubShell.module.less";

type Props = {
  children: ReactNode;
  navigation: { id: Section; label: string; icon: LucideIcon }[];
  section: Section;
  onNavigate: (section: Section) => void;
  username?: string;
  role?: string;
  runtimeCount?: number;
  healthy: boolean;
  isDark: boolean;
  onToggleTheme: () => void;
  onLogout: () => void;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  loading: boolean;
};

export default function HubShell(props: Props) {
  const { t } = useTranslation();
  const screens = Grid.useBreakpoint();
  const mobile = screens.md === false;
  const [open, setOpen] = useState(false);
  const order: Section[] = [
    "overview",
    "runtimes",
    "users",
    "models",
    "credentials",
    "audit",
    "settings",
  ];
  const navigation = [...props.navigation].sort(
    (a, b) => order.indexOf(a.id) - order.indexOf(b.id),
  );
  const themeLabel = t(
    props.isDark ? "hub.actions.useLightTheme" : "hub.actions.useDarkTheme",
  );
  const healthLabel = t(
    props.healthy
      ? "hub.overview.systemHealthy"
      : "hub.overview.systemDegraded",
  );
  const sidebar = (
    <>
      <div className={styles.brand}>
        <span>
          <Activity size={23} />
        </span>
        <div>
          <strong>
            QwenPaw <b>Hub</b>
          </strong>
          <small>{t("hub.brand.controlPlane")}</small>
        </div>
      </div>
      <div className={styles.workspace}>
        <span className={styles.workspaceMark}>Q</span>
        <span>
          QwenPaw<small>{t("hub.overview.localIsolation")}</small>
        </span>
      </div>
      <nav
        className={styles.navigation}
        aria-label={t("hub.navigation.workspace")}
      >
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            type="button"
            key={id}
            className={props.section === id ? styles.selected : undefined}
            aria-label={label}
            aria-current={props.section === id ? "page" : undefined}
            onClick={() => {
              setOpen(false);
              props.onNavigate(id);
            }}
          >
            <Icon size={19} strokeWidth={1.7} />
            <span>{label}</span>
            {id === "runtimes" && props.runtimeCount !== undefined && (
              <small>{props.runtimeCount}</small>
            )}
          </button>
        ))}
      </nav>
      <div className={styles.sidebarFooter}>
        <div className={styles.connection}>
          <i data-healthy={props.healthy} />
          <span>{healthLabel}</span>
        </div>
        <button
          className={styles.back}
          type="button"
          onClick={() => window.location.assign("/")}
        >
          <House size={17} />
          {t("hub.actions.backToQwenPaw")}
        </button>
        <div className={styles.account}>
          <span className={styles.avatar}>
            {(props.username || "Q").slice(0, 2).toUpperCase()}
          </span>
          <div>
            <strong>{props.username || t("common.loading")}</strong>
            <small>{props.role ? t(`hub.roles.${props.role}`) : ""}</small>
          </div>
        </div>
        <div className={styles.accountActions}>
          <LanguageSwitcher persistRemotely={false} />
          <button
            type="button"
            aria-label={themeLabel}
            title={themeLabel}
            onClick={props.onToggleTheme}
          >
            {props.isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            type="button"
            aria-label={t("login.logout")}
            title={t("login.logout")}
            onClick={props.onLogout}
          >
            <LogOut size={18} />
          </button>
        </div>
      </div>
    </>
  );
  return (
    <div className={styles.shell}>
      {mobile ? (
        <Drawer
          className={styles.drawer}
          title={t("hub.navigation.workspace")}
          placement="left"
          closeIcon={<X size={18} />}
          width={288}
          open={open}
          onClose={() => setOpen(false)}
        >
          {sidebar}
        </Drawer>
      ) : (
        <aside className={styles.sidebar}>{sidebar}</aside>
      )}
      <div className={styles.main}>
        <header className={styles.topbar}>
          {mobile && (
            <button
              type="button"
              className={styles.menu}
              aria-label={t("hub.navigation.workspace")}
              aria-expanded={open}
              onClick={() => setOpen(true)}
            >
              <Menu size={21} />
            </button>
          )}
          <div className={styles.breadcrumb}>
            <span>{t("hub.brand.controlPlane")}</span>
            <ChevronRight size={14} />
            <strong>
              {navigation.find((n) => n.id === props.section)?.label}
            </strong>
          </div>
          <div className={styles.topbarActions}>
            <span className={styles.health}>
              <i data-healthy={props.healthy} />
              {healthLabel}
            </span>
            {props.section !== "models" && (
              <Button
                icon={<RefreshCw size={17} />}
                aria-label={t("common.refresh")}
                title={t("common.refresh")}
                loading={props.refreshing}
                disabled={props.loading}
                onClick={props.onRefresh}
              />
            )}
          </div>
        </header>
        <main className={styles.content}>{props.children}</main>
      </div>
    </div>
  );
}
