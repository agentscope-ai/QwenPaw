import React, { useState, useCallback, useRef, useEffect } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Loader2, Search, ChevronRight, X } from "lucide-react";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import styles from "./index.module.less";

interface ChatSearchPanelProps {
  open: boolean;
  onClose: () => void;
}

/** Extract plain text from message content for search */
const extractTextFromContent = (content: unknown): string => {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return (content as Array<{ type: string; text?: string }>)
    .filter((c) => c.type === "text" && c.text)
    .map((c) => c.text || "")
    .join("\n");
};

/** Get role label for message */
const getRoleLabel = (role: string, t: (key: string) => string): string => {
  if (role === "user") {
    return t("chat.search.userMessage");
  }
  return t("chat.search.assistantMessage");
};

interface SearchResult {
  chatId: string;
  chatName: string;
  messageId?: string;
  role: string;
  roleLabel: string;
  text: string;
  matchedText: string;
  timestamp?: string | null;
}

/** Format timestamp for display */
const formatTimestamp = (raw: string | null | undefined): string => {
  if (!raw) return "";
  const date = new Date(raw);
  if (isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const ChatSearchPanel: React.FC<ChatSearchPanelProps> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { sessions, setCurrentSessionId } = useChatAnywhereSessionsState();
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  /** Search progress text, e.g. "3/50" */
  const [searchProgress, setSearchProgress] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Monotonic id so slow list/getChat responses cannot overwrite a newer search. */
  const searchSeqRef = useRef(0);

  // Clean up on unmount: clear timers and release result data
  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
      setSearchResults([]);
      setSearchQuery("");
    };
  }, []);

  // Focus input when drawer opens
  useEffect(() => {
    if (open) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    } else {
      setSearchQuery("");
      setSearchResults([]);
      setSearchProgress("");
    }
  }, [open]);

  // Search across all sessions — serial streaming to avoid memory explosion
  useEffect(() => {
    const seq = ++searchSeqRef.current;

    if (!searchQuery.trim()) {
      setSearchResults([]);
      setSearchProgress("");
      setLoading(false);
      return;
    }

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(async () => {
      setLoading(true);
      setSearchProgress("");
      try {
        const query = searchQuery.toLowerCase();
        const results: SearchResult[] = [];

        const chats = await chatApi.listChats();
        if (seq !== searchSeqRef.current) return;

        const validChats = chats.filter(
          (chat): chat is typeof chat & { id: string } => !!chat.id,
        );
        const totalChats = validChats.length;

        // Serial iteration: load one chat at a time, search, then discard
        for (let chatIndex = 0; chatIndex < totalChats; chatIndex++) {
          if (seq !== searchSeqRef.current) return;

          const chat = validChats[chatIndex];
          const chatId = chat.id;
          const chatName = chat.name || "New Chat";
          const chatTimestamp = chat.created_at;

          setSearchProgress(`${chatIndex + 1}/${totalChats}`);

          // Title match
          if (chat.name && chatName.toLowerCase().includes(query)) {
            results.push({
              chatId,
              chatName,
              role: "chat_title",
              roleLabel: t("chat.search.titleMatch"),
              text: chatName,
              matchedText: chatName,
              timestamp: chatTimestamp,
            });
          }

          // Load this chat's messages, search, then let GC reclaim
          try {
            const history = await chatApi.getChat(chatId);
            if (seq !== searchSeqRef.current) return;

            const messages = history.messages || [];
            for (const msg of messages) {
              const text = extractTextFromContent(msg.content);
              const lowerText = text.toLowerCase();
              if (lowerText.includes(query)) {
                const matchIndex = lowerText.indexOf(query);
                const contextLength = 80;
                const start = Math.max(0, matchIndex - contextLength);
                const end = Math.min(
                  text.length,
                  matchIndex + searchQuery.length + contextLength,
                );
                const matchedText = text.slice(start, end);

                results.push({
                  chatId,
                  chatName,
                  messageId: String(msg.id || ""),
                  role: msg.role || "",
                  roleLabel: getRoleLabel(msg.role || "", t),
                  text: "",
                  matchedText: start > 0 ? `...${matchedText}` : matchedText,
                  timestamp: chatTimestamp,
                });
              }
            }
            // history and messages go out of scope here — GC can reclaim
          } catch (err) {
            console.warn(`Failed to load chat ${chatId}:`, err);
          }

          // Flush intermediate results every 5 chats for progressive UX
          if ((chatIndex + 1) % 5 === 0 || chatIndex === totalChats - 1) {
            if (seq !== searchSeqRef.current) return;
            const sorted = [...results].sort((a, b) => {
              if (!a.timestamp && !b.timestamp) return 0;
              if (!a.timestamp) return 1;
              if (!b.timestamp) return -1;
              return (
                new Date(b.timestamp!).getTime() -
                new Date(a.timestamp!).getTime()
              );
            });
            setSearchResults(sorted);
          }
        }

        if (seq !== searchSeqRef.current) return;

        // Final sort and update
        results.sort((a, b) => {
          if (!a.timestamp && !b.timestamp) return 0;
          if (!a.timestamp) return 1;
          if (!b.timestamp) return -1;
          return (
            new Date(b.timestamp!).getTime() - new Date(a.timestamp!).getTime()
          );
        });

        setSearchResults(results);
      } catch (err) {
        if (seq !== searchSeqRef.current) return;
        console.error("Search failed:", err);
        setSearchResults([]);
      } finally {
        if (seq === searchSeqRef.current) {
          setLoading(false);
          setSearchProgress("");
        }
      }
    }, 300);

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
      }
    };
  }, [searchQuery, t]);

  // Navigate to chat when clicking result
  const handleResultClick = useCallback(
    (result: SearchResult) => {
      // Find the session in the local list
      const session = sessions.find((s) => {
        const realId = sessionApi.getRealIdForSession(s.id || "");
        return realId === result.chatId || s.id === result.chatId;
      });

      if (session?.id) {
        // Switch to that session
        setCurrentSessionId(session.id);
        // Navigate to the chat URL
        navigate(`/chat/${session.id}`);
      } else {
        // Session not in local list, navigate by chat ID directly
        navigate(`/chat/${result.chatId}`);
      }

      onClose();
    },
    [sessions, setCurrentSessionId, navigate, onClose],
  );

  return (
    <Sheet
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <SheetContent
        side="right"
        className={`w-[360px] p-0 flex flex-col h-full overflow-hidden ${
          styles.drawer ?? ""
        }`}
      >
        <SheetHeader className="sr-only">
          <SheetTitle>{t("chat.search.title") || "Search"}</SheetTitle>
          <SheetDescription>
            {t("chat.search.title") || "Search chat sessions"}
          </SheetDescription>
        </SheetHeader>
        {/* Header bar */}
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <span className={styles.headerTitle}>{t("chat.search.title")}</span>
          </div>
          <div className={styles.headerRight}>
            <button
              type="button"
              className="inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              onClick={onClose}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {/* Search input */}
        <div className={styles.searchSection}>
          <div className="relative flex items-center">
            <Search
              size={14}
              className="absolute left-3 text-muted-foreground pointer-events-none"
            />
            <input
              ref={inputRef}
              placeholder={t("chat.search.placeholder")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`${styles.searchInput} pl-8 pr-8`}
            />
            {searchQuery && (
              <button
                type="button"
                className="absolute right-3 text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => {
                  setSearchQuery("");
                  inputRef.current?.focus();
                }}
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Results count / search progress */}
        {searchQuery.trim() && (
          <div className={styles.resultsCount}>
            <span className="text-sm text-muted-foreground">
              {loading && searchProgress
                ? t("chat.search.searching", { progress: searchProgress })
                : loading
                ? t("chat.search.loading")
                : t("chat.search.resultsCount", {
                    count: searchResults.length,
                  })}
            </span>
          </div>
        )}

        {/* Results list */}
        <div className={styles.listWrapper}>
          <div className={styles.topGradient} />
          <div className={styles.list}>
            {loading && searchResults.length === 0 ? (
              <div className="flex justify-center p-10">
                <Loader2
                  size={20}
                  className="animate-spin text-muted-foreground"
                />
              </div>
            ) : searchQuery.trim() && !loading && searchResults.length === 0 ? (
              <div className="flex flex-col items-center justify-center mt-10 text-sm text-muted-foreground gap-2">
                <Search size={32} className="opacity-30" />
                {t("chat.search.noResults")}
              </div>
            ) : (
              <div>
                {searchResults.map((item, idx) => (
                  <div
                    key={`${item.chatId}-${item.messageId ?? idx}`}
                    className={styles.searchResultItem}
                    onClick={() => handleResultClick(item)}
                  >
                    <div className={styles.resultHeader}>
                      <span className={styles.resultChatName}>
                        {item.chatName}
                      </span>
                      <span className={styles.resultRole}>
                        {item.roleLabel}
                      </span>
                    </div>
                    <div className={styles.resultContent}>
                      <span className="text-[13px] line-clamp-2">
                        {item.matchedText}
                      </span>
                    </div>
                    {item.timestamp && (
                      <div className={styles.resultTime}>
                        {formatTimestamp(item.timestamp)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className={styles.bottomGradient} />
        </div>
      </SheetContent>
    </Sheet>
  );
};

export default ChatSearchPanel;
