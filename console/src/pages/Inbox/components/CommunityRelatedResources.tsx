import { useEffect, useState } from "react";
import { Button, Space, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "@/api/request";
import { openExternalLink } from "@/utils/openExternalLink";
import {
  getCommunityMessageDetail,
  safeCommunityDiscussionUrl,
} from "../utils/community";

interface Resource {
  id: string;
  type: "skill" | "plugin";
  name: string;
  url: string;
}
type Detail = NonNullable<ReturnType<typeof getCommunityMessageDetail>>;

export function CommunityRelatedResources({ detail }: { detail: Detail }) {
  const { t } = useTranslation();
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const { discussionUrl, resourceType, resourceId, resourceName } = detail;
  useEffect(() => {
    const controller = new AbortController();
    setResources([]);
    setFailed(false);
    const postId = discussionUrl
      ? new URL(discussionUrl).pathname.match(
          /^\/community\/articles\/([A-Za-z0-9_-]+)\/?$/,
        )?.[1]
      : undefined;
    if (!postId) {
      setLoading(false);
      if (["skill", "plugin", "app"].includes(resourceType) && resourceId) {
        const type = resourceType === "skill" ? "skill" : "plugin";
        setResources([
          {
            id: resourceId,
            type,
            name: resourceName || resourceId,
            url: `https://platform.agentscope.io/${
              type === "skill" ? "skills" : "plugins"
            }/${encodeURIComponent(resourceId)}`,
          },
        ]);
      }
      return () => controller.abort();
    }
    setLoading(true);
    request<{ resources: Resource[] }>(
      `/community/posts/${encodeURIComponent(postId)}/resources`,
      { signal: controller.signal },
    )
      .then((data) => {
        if (!controller.signal.aborted) setResources(data.resources);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [discussionUrl, resourceType, resourceId, resourceName, reload]);
  if (loading) return <Spin size="small" />;
  if (failed)
    return (
      <Space>
        <span>{t("communityInbox.resourcesFailed")}</span>
        <Button size="small" onClick={() => setReload((value) => value + 1)}>
          {t("communityPage.retry")}
        </Button>
      </Space>
    );
  const links = resources.filter(
    (resource) =>
      ["skill", "plugin"].includes(resource.type) &&
      safeCommunityDiscussionUrl(resource.url),
  );
  if (!links.length) return <span>{t("communityInbox.noResources")}</span>;
  return (
    <Space direction="vertical" size={4}>
      {links.map((resource) => (
        <a
          key={`${resource.type}:${resource.id}`}
          href={resource.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            event.preventDefault();
            openExternalLink(resource.url);
          }}
        >
          {resource.name} ({resource.type === "skill" ? "Skill" : "Plugin"})
        </a>
      ))}
    </Space>
  );
}
