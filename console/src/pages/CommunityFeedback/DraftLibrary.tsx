import { useEffect, useState } from "react";
import { Alert, Button, Empty, Popconfirm, Spin, Tag, Pagination } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { communityConnectionApi } from "@/api/modules/community";
import { listPostDrafts, removePostDraft, type PostDraft } from "./postDrafts";
import { listPostDrafts as listLegacyDrafts } from "./legacyPostDrafts";
import { savePostDraft } from "./postDrafts";
import styles from "./index.module.less";

export function DraftLibrary({
  onOpen,
  onBack,
}: {
  onOpen: (draft: PostDraft) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [account, setAccount] = useState<string>();
  const [items, setItems] = useState<PostDraft[]>([]);
  const [legacy, setLegacy] = useState<PostDraft[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [mutating, setMutating] = useState(false);
  const [legacyError, setLegacyError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    communityConnectionApi
      .status()
      .then(async (status) => {
        if (!active) return;
        if (status.status === "connected" && status.account) {
          setAccount(status.account.id);
          try {
            setLegacy(listLegacyDrafts(status.account.id));
          } catch {
            setLegacyError(true);
          }
          const result = await listPostDrafts(status.account.id, page);
          if (!active) return;
          setItems(result.items);
          setTotal(result.total);
        } else {
          setAccount(undefined);
          setItems([]);
          setLegacy([]);
          setTotal(0);
        }
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, revision]);
  const remove = async (id: string) => {
    if (!account) return;
    setMutating(true);
    try {
      await removePostDraft(account, id);
      if (items.length === 1 && page > 1) setPage(page - 1);
      else setRevision((value) => value + 1);
    } catch {
      setError(true);
    } finally {
      setMutating(false);
    }
  };
  const importLegacy = async (draft: PostDraft) => {
    if (!account) return;
    setMutating(true);
    try {
      const saved = await savePostDraft(account, draft);
      // Retain the original browser draft, including local-only instructions.
      onOpen(saved);
    } catch {
      setError(true);
    } finally {
      setMutating(false);
    }
  };
  return (
    <section className={styles.draftLibrary}>
      <Button type="text" onClick={onBack}>
        {t("communityPage.back")}
      </Button>
      <h1>{t("communityDrafts.title")}</h1>
      <p className={styles.hint}>{t("communityDrafts.help")}</p>
      {error && (
        <Alert
          type="error"
          message={t("communityDrafts.failed")}
          action={
            <Button onClick={() => setRevision((value) => value + 1)}>
              {t("communityPage.refresh")}
            </Button>
          }
        />
      )}
      {legacyError && (
        <Alert type="warning" message={t("communityDrafts.legacyFailed")} />
      )}
      <Spin spinning={loading || mutating}>
        {!loading &&
          !error &&
          (!account ? (
            <Link to="/settings/community">
              {t("communityCompose.loginRequired")}
            </Link>
          ) : !items.length ? (
            <Empty description={t("communityDrafts.empty")} />
          ) : (
            items.map((item) => (
              <article key={item.id} className={styles.draftCard}>
                <div>
                  <Tag>{t(`communityPage.${item.type}`)}</Tag>
                  <span className={styles.hint}>
                    {new Date(item.updatedAt).toLocaleString()}
                  </span>
                </div>
                <h2>{item.title || t("communityDrafts.untitled")}</h2>
                <p>{item.content.slice(0, 160) || item.instructions}</p>
                <div className={styles.actions}>
                  <Button onClick={() => onOpen(item)}>
                    {t("communityDrafts.edit")}
                  </Button>
                  <Popconfirm
                    title={t("communityDrafts.deleteConfirm")}
                    onConfirm={() => remove(item.id)}
                  >
                    <Button type="text" danger>
                      {t("common.delete")}
                    </Button>
                  </Popconfirm>
                </div>
              </article>
            ))
          ))}
        {account && total > 20 && (
          <Pagination
            current={page}
            total={total}
            pageSize={20}
            showSizeChanger={false}
            onChange={setPage}
          />
        )}
        {account && legacy.length > 0 && (
          <>
            <h2>{t("communityDrafts.legacyTitle")}</h2>
            <p className={styles.hint}>{t("communityDrafts.legacyHelp")}</p>
            {legacy.map((item) => (
              <article className={styles.draftCard} key={item.id}>
                <h3>{item.title || t("communityDrafts.untitled")}</h3>
                <p>{item.content.slice(0, 160) || item.instructions}</p>
                <Button
                  disabled={mutating}
                  onClick={() => void importLegacy(item)}
                >
                  {t("communityDrafts.import")}
                </Button>
              </article>
            ))}
          </>
        )}
      </Spin>
    </section>
  );
}
