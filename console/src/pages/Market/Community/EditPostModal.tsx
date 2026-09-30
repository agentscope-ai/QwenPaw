import { useState } from "react";
import { Alert, Button, Checkbox, Input, Modal, Space } from "antd";
import { useTranslation } from "react-i18next";
import { communityErrorKey } from "@/utils/communityError";
import { communityPostsApi, type Post } from "./api";
import { PostBody } from "./PostBody";

export function EditPostModal({
  post,
  accountId,
  onClose,
  onSaved,
}: {
  post: Post;
  accountId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(post.title);
  const [content, setContent] = useState(post.body_text || "");
  const [preview, setPreview] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    if (!confirmed || busy) return;
    setBusy(true);
    setError("");
    try {
      await communityPostsApi.update(post.id, accountId, title, content);
      onSaved();
    } catch (err) {
      setError(communityErrorKey(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title={t("communityPage.editPost")}
      width={800}
      maskClosable={false}
      onCancel={busy ? undefined : onClose}
      footer={
        <Space wrap>
          <Checkbox
            checked={confirmed}
            disabled={busy}
            onChange={(e) => setConfirmed(e.target.checked)}
          >
            {t("communityPage.confirmEdit")}
          </Checkbox>
          <Button
            type="primary"
            disabled={!confirmed || !title.trim() || !content.trim()}
            loading={busy}
            onClick={() => void save()}
          >
            {t("communityPage.saveEdit")}
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error && <Alert type="error" message={t(error)} />}
        <label htmlFor="edit-post-title">
          {t("communityCompose.postTitle")}
        </label>
        <Input
          id="edit-post-title"
          value={title}
          maxLength={256}
          disabled={busy}
          onChange={(e) => {
            setTitle(e.target.value);
            setConfirmed(false);
          }}
        />
        <Space>
          <label htmlFor="edit-post-body">{t("communityCompose.body")}</label>
          <Button size="small" onClick={() => setPreview(!preview)}>
            {t(preview ? "communityAssist.edit" : "communityAssist.preview")}
          </Button>
        </Space>
        {preview ? (
          <div style={{ maxHeight: "55vh", overflow: "auto" }}>
            <PostBody
              post={{ ...post, body_html: undefined, body_text: content }}
            />
          </div>
        ) : (
          <Input.TextArea
            id="edit-post-body"
            rows={16}
            value={content}
            maxLength={65536}
            disabled={busy}
            onChange={(e) => {
              setContent(e.target.value);
              setConfirmed(false);
            }}
          />
        )}
      </Space>
    </Modal>
  );
}
