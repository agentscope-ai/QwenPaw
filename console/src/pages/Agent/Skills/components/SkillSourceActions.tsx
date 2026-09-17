import { invalidateSkillCache } from "@/api/modules/skill";
import type { SkillSpec } from "@/api/types";
import { Alert, Button, Space, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { createSkillGovernanceApi } from "@/api/modules/skillGovernance";
import {
  confirmSkillAction,
  skillErrorMessage,
  useSkillRuntime,
} from "../useSkillRuntime";

export function SkillSourceActions({
  skill,
  onChanged,
}: {
  skill: SkillSpec;
  onChanged: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { scope, modal, message } = useSkillRuntime();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    setBusy(false);
    setError("");
    pending.current = false;
  }, [scope]);
  const bound = !!skill.source_pool_version_id;
  const run = async (action: "update" | "restore") => {
    if (
      !scope.canEdit ||
      !scope.current() ||
      !skill.content_hash ||
      pending.current
    )
      return;
    pending.current = true;
    const hash = skill.content_hash;
    const confirmed = await confirmSkillAction(scope, modal, {
      title: t(`skillGovernance.${action}`),
      content: (
        <Space direction="vertical">
          <span>
            {t("skillGovernance.overwriteWarning", { name: skill.name })}
          </span>
          <Typography.Text code>{hash}</Typography.Text>
        </Space>
      ),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
    });
    if (!confirmed) {
      pending.current = false;
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createSkillGovernanceApi(scope)[action](skill.name, hash);
      if (!scope.current()) return;
      message.success(t("skillGovernance.completed"));
      invalidateSkillCache({ agentId: scope.agentId });
      await onChanged();
    } catch (error) {
      if (!scope.current()) return;
      setError(skillErrorMessage(error, t));
      invalidateSkillCache({ agentId: scope.agentId });
      await onChanged();
    } finally {
      if (scope.current()) {
        setBusy(false);
        pending.current = false;
      }
    }
  };
  return (
    <div onClick={(event) => event.stopPropagation()}>
      <Space wrap size="small">
        <Tag>
          {bound
            ? t("skillGovernance.sourceVersion", {
                version: skill.source_pool_version ?? "—",
              })
            : t("skillGovernance.private")}
        </Tag>
        {bound && skill.detached && (
          <Tag color="orange">{t("skillGovernance.recoverable")}</Tag>
        )}
        {bound && skill.update_available && (
          <Tag color="blue">{t("skillGovernance.updateAvailable")}</Tag>
        )}
        {scope.multiUser && scope.canEdit && bound && skill.content_hash && (
          <>
            {skill.update_available && (
              <Button
                size="small"
                disabled={busy}
                onClick={() => void run("update")}
              >
                {t("skillGovernance.update")}
              </Button>
            )}
            {skill.detached && (
              <Button
                size="small"
                disabled={busy}
                onClick={() => void run("restore")}
              >
                {t("skillGovernance.restore")}
              </Button>
            )}
          </>
        )}
      </Space>
      {error && <Alert type="error" showIcon message={error} />}
    </div>
  );
}
