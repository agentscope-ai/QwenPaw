import { useEffect, useState } from "react";
import { Button, Input, Spin, Tooltip } from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "@/api";
import { useAutoSave } from "@/hooks/useAutoSave";
import styles from "./index.module.less";

export function HeartbeatInstructions({ agentId }: { agentId: string }) {
  const { t } = useTranslation();
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { schedule } = useAutoSave(async () => {
    await api.saveFile("HEARTBEAT.md", content, agentId);
  });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    api
      .loadFile("HEARTBEAT.md", agentId)
      .then(
        (file) => {
          if (active) setContent(file.content);
        },
        (error: { status?: number }) => {
          if (!active) return;
          if (error.status === 404) setContent("");
          else setFailed(true);
        },
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [agentId, attempt]);
  return (
    <section className={styles.instructions}>
      <header>
        <h2>HEARTBEAT.md</h2>
        <Tooltip title={t("heartbeat.description")}>
          <button type="button" aria-label={t("heartbeat.description")}>
            <CircleHelp size={16} />
          </button>
        </Tooltip>
      </header>
      {loading ? (
        <Spin />
      ) : failed ? (
        <Button onClick={() => setAttempt((value) => value + 1)}>
          {t("common.retry")}
        </Button>
      ) : (
        <Input.TextArea
          aria-label="HEARTBEAT.md"
          value={content}
          rows={10}
          spellCheck={false}
          onChange={(event) => {
            setContent(event.target.value);
            schedule();
          }}
        />
      )}
    </section>
  );
}
