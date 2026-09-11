import { useRef, useState } from "react";
import { Alert, Button, Modal, Space } from "antd";
import { useRequest } from "ahooks";
import { useTranslation } from "react-i18next";
import {
  mailAccessControlApi,
  type MailProcessingPause,
} from "../../../api/modules/mailAccessControl";
import { useAppMessage } from "../../../hooks/useAppMessage";

/** Live safety controls remain available even if the inbox alert was deleted. */
export function MailProcessingPauses() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [selected, setSelected] = useState<MailProcessingPause | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const {
    data: pauses = [],
    error,
    refresh,
  } = useRequest(mailAccessControlApi.getMailProcessingPauses, {
      pollingInterval: 6000,
      pollingWhenHidden: false,
    onError: () => {}, // Retain current pauses and show one persistent error.
  });

  const resume = async () => {
    if (!selected || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await mailAccessControlApi.resumeMailProcessing(
        selected.agent_id,
        selected.pause_id,
      );
      message.success(t("inbox.mailProcessingResumed"));
    } catch {
      message.error(t("inbox.mailProcessingResumeFailed"));
    } finally {
      setSelected(null);
      submittingRef.current = false;
      setSubmitting(false);
      refresh();
    }
  };

  return (
    <>
      <Space direction="vertical" style={{ width: "100%" }}>
        {error && (
          <Alert
            type="error"
            showIcon
            message={t("inbox.mailProcessingLoadFailed")}
            action={<Button onClick={refresh}>{t("common.retry")}</Button>}
          />
        )}
        {pauses.map((pause) => (
          <Alert
            key={`${pause.agent_id}:${pause.pause_id}`}
            showIcon
            type={pause.reason === "batch" ? "warning" : "error"}
            message={t("inbox.mailProcessingPaused", { agent: pause.agent_id })}
            description={t(`inbox.mailProcessingReason_${pause.reason}`, {
              count: pause.count,
            })}
            action={
              <Button onClick={() => setSelected(pause)} disabled={submitting}>
                {t("inbox.mailProcessingReview")}
              </Button>
            }
          />
        ))}
      </Space>
      <Modal
        open={selected !== null}
        title={t("inbox.mailProcessingPaused", { agent: selected?.agent_id })}
        onOk={resume}
        onCancel={() => setSelected(null)}
        confirmLoading={submitting}
        cancelButtonProps={{ disabled: submitting }}
        closable={!submitting}
        maskClosable={!submitting}
        keyboard={!submitting}
        okText={t(
          selected?.reason === "batch"
            ? "inbox.mailProcessingConfirmBatch"
            : "inbox.mailProcessingConfirmResume",
          { count: selected?.count },
        )}
        cancelText={t("inbox.mailProcessingKeepPaused")}
      >
        {t(
          selected?.reason === "batch"
            ? "inbox.mailProcessingBatchConfirm"
            : "inbox.mailProcessingResumeConfirm",
          { count: selected?.count },
        )}
      </Modal>
    </>
  );
}
