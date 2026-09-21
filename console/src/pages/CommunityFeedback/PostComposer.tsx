import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { request } from "@/api/request";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { COMMUNITY_POST_TYPES } from "@/constants/community";
import {
  reserveAuthorizationWindow,
  openAuthorizationUrl,
} from "@/utils/communityAuthorization";
import { communityErrorKey } from "@/utils/communityError";
import type { InstallationOrigin } from "@/api/types/community";

export function PostComposer({
  onClose,
  initialBody = "",
  origin,
  resourceName,
}: {
  onClose: () => void;
  initialBody?: string;
  origin?: InstallationOrigin;
  resourceName?: string;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CommunityConnectionStatus>();
  const [title, setTitle] = useState(
    initialBody.match(/^#\s+(.+)/)?.[1]?.slice(0, 256) || "",
  );
  const [content, setContent] = useState(initialBody);
  const [type, setType] = useState("question");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [published, setPublished] = useState<string>();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const refresh = () =>
      communityConnectionApi
        .status()
        .then((value) => {
          if (mounted.current) setStatus(value);
        })
        .catch((err) => {
          if (mounted.current) setError(communityErrorKey(err));
        });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, []);
  const login = async () => {
    let popup: Window | null = null;
    setBusy(true);
    setError(undefined);
    try {
      popup = reserveAuthorizationWindow(t("community.waiting"));
      const flow = await communityConnectionApi.start();
      try {
        if (!mounted.current) throw new Error("authorization_cancelled");
        await openAuthorizationUrl(flow.authorize_url, popup);
      } catch (err) {
        await communityConnectionApi.cancel(flow.flow_id).catch(() => {});
        throw err;
      }
    } catch (err) {
      popup?.close();
      if (mounted.current) setError(communityErrorKey(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const publish = async () => {
    if (!status?.account || !confirmed || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await request<{ id: string }>("/community/posts", {
        method: "POST",
        body: JSON.stringify({
          title,
          content,
          article_type: type,
          account_id: status.account.id,
          origin,
        }),
      });
      setPublished(result.id);
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setBusy(false);
    }
  };
  const connected = status?.status === "connected";
  return (
    <Modal
      open
      title={t(
        origin ? "communityFeedback.reportIssue" : "communityCompose.title",
      )}
      width={760}
      maskClosable={false}
      onCancel={busy ? undefined : onClose}
      footer={null}
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {error && (
          <Alert
            type="error"
            message={t(error)}
            description={t("communityCompose.error")}
          />
        )}
        {published ? (
          <Alert
            type="success"
            message={t("communityCompose.published")}
            description={
              <a
                href={`/market?tab=community&post=${encodeURIComponent(
                  published,
                )}`}
              >
                {t("communityCompose.view")}
              </a>
            }
          />
        ) : !status ? (
          <Spin />
        ) : !connected ? (
          <>
            <Alert
              type="info"
              message={t("communityCompose.loginRequired")}
              description={t("communityCompose.loginHelp")}
            />
            <Button type="primary" loading={busy} onClick={() => void login()}>
              {t("communityCompose.login")}
            </Button>
          </>
        ) : (
          <>
            <Typography.Text type="secondary">
              {t("communityCompose.account", {
                name: status.account?.display_name,
              })}
            </Typography.Text>
            {origin && (
              <Alert
                type="info"
                message={`${t("communityInbox.resource")}: ${
                  resourceName || origin.resource_id
                }`}
              />
            )}
            <label htmlFor="community-post-type">
              {t("communityPage.type")}
            </label>
            <Select
              id="community-post-type"
              value={type}
              onChange={setType}
              disabled={busy}
              options={COMMUNITY_POST_TYPES.map((value) => ({
                value,
                label: t(`communityPage.${value}`),
              }))}
            />
            <label htmlFor="community-post-title">
              {t("communityCompose.postTitle")}
            </label>
            <Input
              id="community-post-title"
              value={title}
              maxLength={256}
              disabled={busy}
              onChange={(event) => {
                setTitle(event.target.value);
                setConfirmed(false);
              }}
            />
            <label htmlFor="community-post-body">
              {t("communityCompose.body")}
            </label>
            <Input.TextArea
              id="community-post-body"
              value={content}
              maxLength={65536}
              autoSize={{ minRows: 10, maxRows: 20 }}
              disabled={busy}
              onChange={(event) => {
                setContent(event.target.value);
                setConfirmed(false);
              }}
            />
            <Checkbox
              checked={confirmed}
              disabled={busy}
              onChange={(event) => setConfirmed(event.target.checked)}
            >
              {t("communityCompose.confirm")}
            </Checkbox>
            <Button
              type="primary"
              loading={busy}
              disabled={!confirmed || !title.trim() || !content.trim()}
              onClick={() => void publish()}
            >
              {t("communityCompose.publish")}
            </Button>
          </>
        )}
      </Space>
    </Modal>
  );
}
