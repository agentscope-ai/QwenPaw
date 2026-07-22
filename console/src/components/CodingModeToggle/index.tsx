import { useCallback, useRef, useState } from "react";
import { Modal, Tooltip } from "antd";
import { Code, FlaskConical, MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useCodingMode, useProjectDir } from "../../stores/codingModeStore";
import { useAgentStore } from "../../stores/agentStore";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";
import { useLocation, useNavigate } from "react-router-dom";
import ProjectSelectModal from "../ProjectSelectModal";
import {
  buildSessionPath,
  getSessionIdFromPath,
} from "../../utils/sessionRoute";
import { useSidebarModeStore } from "../../stores/sidebarModeStore";
import styles from "./index.module.less";

const CONFIRMED_KEY = "qwenpaw-coding-mode-confirmed";

export default function CodingModeToggle() {
  const { t } = useTranslation();
  const { codingMode, initialized, setCodingMode } = useCodingMode();
  const { selectedAgent } = useAgentStore();
  const navigate = useNavigate();
  const location = useLocation();
  const { projectDir } = useProjectDir();
  const { setMode: setSidebarMode } = useSidebarModeStore();
  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showProjectSelect, setShowProjectSelect] = useState(false);
  /** Remember sidebar mode before switching to coding, so we can restore on exit */
  const previousSidebarModeRef = useRef<"simple" | "full" | null>(null);

  const activate = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(getApiUrl("/coding-mode"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
          "X-Agent-Id": selectedAgent,
        },
        body: JSON.stringify({ enabled: true }),
      });
      setCodingMode(true);
      setSidebarMode("simple");
      const currentSessionId = getSessionIdFromPath(location.pathname);
      navigate(buildSessionPath("coding", currentSessionId));
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }, [
    loading,
    selectedAgent,
    setCodingMode,
    setSidebarMode,
    navigate,
    location.pathname,
  ]);

  const deactivate = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(getApiUrl("/coding-mode"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
          "X-Agent-Id": selectedAgent,
        },
        body: JSON.stringify({ enabled: false }),
      });
      setCodingMode(false);
      // Restore sidebar mode to what it was before entering coding mode
      if (previousSidebarModeRef.current) {
        setSidebarMode(previousSidebarModeRef.current);
        previousSidebarModeRef.current = null;
      }
      const currentSessionId = getSessionIdFromPath(location.pathname);
      navigate(buildSessionPath("chat", currentSessionId));
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }, [
    loading,
    selectedAgent,
    setCodingMode,
    setSidebarMode,
    navigate,
    location.pathname,
  ]);

  const toggle = useCallback(async () => {
    if (codingMode) {
      // Exiting doesn't need confirmation
      await deactivate();
      return;
    }
    // Remember current sidebar mode before switching to coding
    previousSidebarModeRef.current = useSidebarModeStore.getState().mode;
    // First-time activation: show experimental warning
    const confirmed = localStorage.getItem(CONFIRMED_KEY);
    if (!confirmed) {
      setShowConfirm(true);
    } else if (projectDir === undefined) {
      // Never selected a project yet → show project picker
      setShowProjectSelect(true);
    } else {
      // null = workspace default, string = specific path → go directly
      await activate();
    }
  }, [codingMode, activate, deactivate, projectDir]);

  const handleConfirm = useCallback(() => {
    localStorage.setItem(CONFIRMED_KEY, "1");
    setShowConfirm(false);
    // After confirming experimental warning, show project selection
    setShowProjectSelect(true);
  }, []);

  const handleProjectConfirm = useCallback(async () => {
    setShowProjectSelect(false);
    await activate();
  }, [activate]);

  return (
    <>
      <Tooltip
        title={
          codingMode
            ? t("codingMode.exitTooltip")
            : t("codingMode.enterTooltip")
        }
        placement="bottom"
      >
        <button
          type="button"
          className={`${styles.toggle} ${codingMode ? styles.active : ""}`}
          onClick={() => void toggle()}
          disabled={loading || !initialized}
          aria-label={
            codingMode
              ? t("codingMode.exitTooltip")
              : t("codingMode.enterTooltip")
          }
        >
          <span className={styles.icon}>
            {codingMode ? <MessageSquare size={14} /> : <Code size={14} />}
          </span>
          <span className={styles.label}>
            {codingMode ? t("codingMode.btnChat") : t("codingMode.btnCode")}
          </span>
        </button>
      </Tooltip>

      {/* Step 1: Experimental warning */}
      <Modal
        open={showConfirm}
        title={
          <span className={styles.modalTitle}>
            <FlaskConical size={16} className={styles.flaskIcon} />
            {t("codingMode.experimental")}
          </span>
        }
        okText={t("codingMode.confirmBtn")}
        cancelText={t("common.cancel")}
        onOk={handleConfirm}
        onCancel={() => setShowConfirm(false)}
        confirmLoading={loading}
        width={440}
      >
        <div className={styles.modalBody}>
          <p className={styles.modalDesc}>{t("codingMode.experimentalDesc")}</p>
          <p className={styles.modalNote}>{t("codingMode.experimentalNote")}</p>
        </div>
      </Modal>

      {/* Step 2: Project selection */}
      <ProjectSelectModal
        open={showProjectSelect}
        onClose={() => {
          // User dismissed → enter with default workspace
          setShowProjectSelect(false);
          void activate();
        }}
        onConfirm={() => void handleProjectConfirm()}
      />
    </>
  );
}
