import { Input, Spin } from "antd";
import { Search, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ConversationSearch } from "./useConversationSearch";
import styles from "./conversationSearch.module.less";

export function ConversationSearchControls({
  search,
  inputClassName,
}: {
  search: ConversationSearch;
  inputClassName?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.controls}>
      <div
        className={styles.modes}
        role="group"
        aria-label={t("chat.historySearch.mode", "Search mode")}
      >
        <button
          type="button"
          aria-pressed={search.mode === "keyword"}
          onClick={() => search.setMode("keyword")}
        >
          <Search size={12} />
          {t("chat.historySearch.keyword", "Keyword")}
        </button>
        <button
          type="button"
          aria-pressed={search.mode === "agent"}
          onClick={() => search.setMode("agent")}
        >
          <Sparkles size={12} />
          {t("chat.historySearch.agent", "AI search")}
        </button>
      </div>
      <Input
        size="small"
        allowClear
        maxLength={500}
        aria-label={t(
          "chat.historySearch.label",
          "Search conversation history",
        )}
        placeholder={
          search.mode === "agent"
            ? t(
                "chat.historySearch.agentPlaceholder",
                "Describe the conversation…",
              )
            : t(
                "chat.historySearch.keywordPlaceholder",
                "Search titles and messages…",
              )
        }
        value={search.query}
        onChange={(event) => search.setQuery(event.target.value)}
        onPressEnter={(event) => {
          if (!event.nativeEvent.isComposing && !search.loading)
            search.submit();
        }}
        className={[styles.input, inputClassName].filter(Boolean).join(" ")}
        suffix={
          search.mode === "agent" ? (
            <button
              type="button"
              className={styles.submit}
              disabled={!search.active || search.loading}
              aria-label={t("chat.historySearch.submit", "Search")}
              title={t("chat.historySearch.submit", "Search")}
              onClick={search.submit}
            >
              <Search size={14} />
            </button>
          ) : undefined
        }
      />
    </div>
  );
}

/** Text nodes and marks only: snippets can contain untrusted HTML or Markdown. */
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const words = [
    ...new Set(terms.map((term) => term.trim()).filter(Boolean)),
  ].sort((a, b) => b.length - a.length);
  if (words.length === 0) return <>{text}</>;
  const pattern = new RegExp(
    `(${words
      .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|")})`,
    "gi",
  );
  return (
    <>
      {text
        .split(pattern)
        .map((part, index) =>
          index % 2 === 1 ? <mark key={index}>{part}</mark> : part,
        )}
    </>
  );
}

export function ConversationSearchResults({
  search,
  currentSessionId,
  onSelect,
}: {
  search: ConversationSearch;
  currentSessionId?: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const response = search.response;
  const terms = response?.queries.length
    ? response.queries
    : [search.query.trim()];
  return (
    <div
      className={styles.results}
      aria-busy={search.loading}
      aria-label={t(
        "chat.historySearch.results",
        "Conversation search results",
      )}
    >
      <div className={styles.status} role="status" aria-live="polite">
        {search.awaitingSubmit &&
          t(
            "chat.historySearch.agentHint",
            "Describe what you remember, then press Enter to search with the current agent's model.",
          )}
        {search.loading && (
          <>
            <Spin size="small" />
            <span>
              {t("chat.historySearch.searching", "Searching conversations…")}
            </span>
          </>
        )}
        {!search.loading &&
          !search.error &&
          response &&
          (response.results.length > 0
            ? t("chat.historySearch.count", "{{count}} conversations", {
                count: response.total,
              })
            : t(
                "chat.sessionPanel.noMatchingConversations",
                "No matching conversations",
              ))}
      </div>
      {response?.partial && (
        <p className={styles.hint}>
          {t(
            "chat.historySearch.partial",
            "Showing partial results. Try a more specific search.",
          )}
        </p>
      )}
      {response?.results.map(({ chat, snippet, role }) => (
        <button
          type="button"
          key={chat.id}
          className={styles.result}
          aria-current={chat.id === currentSessionId ? "page" : undefined}
          onClick={() => onSelect(chat.id)}
        >
          <span className={styles.title}>
            <Highlight
              text={chat.name || t("chat.newChat", "New Chat")}
              terms={terms}
            />
          </span>
          <span className={styles.snippet}>
            <span className={styles.role}>
              {role === "user"
                ? t("chat.search.userMessage", "User")
                : role === "assistant"
                ? t("chat.search.assistantMessage", "Assistant")
                : t("chat.search.titleMatch", "Title")}
              :{" "}
            </span>
            <Highlight text={snippet} terms={terms} />
          </span>
        </button>
      ))}
      {search.error && (
        <div className={styles.error} role="alert">
          <span>
            {search.mode === "agent"
              ? t(
                  "chat.historySearch.agentError",
                  "AI search failed. Check the current agent's model configuration or try keyword search.",
                )
              : t(
                  "chat.historySearch.error",
                  "Could not search conversations. Try again.",
                )}
          </span>
          <button
            type="button"
            className={styles.action}
            onClick={response ? search.loadMore : search.submit}
          >
            {t("common.retry", "Retry")}
          </button>
        </div>
      )}
      {search.mode === "keyword" && response?.has_more && !search.error && (
        <button
          type="button"
          className={styles.action}
          disabled={search.loading}
          onClick={search.loadMore}
        >
          {t("chat.historySearch.loadMore", "Load more")}
        </button>
      )}
    </div>
  );
}
