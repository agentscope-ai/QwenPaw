import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { Drawer, Input, List, Typography, Empty } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine, SparkSearchLine } from "@agentscope-ai/icons";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

interface ChatSearchPanelProps {
  open: boolean;
  onClose: () => void;
}

/** Extract plain text from message content for search */
const extractMessageText = (msg: IAgentScopeRuntimeWebUIMessage): string => {
  const texts: string[] = [];

  // Extract from cards
  if (msg.cards) {
    for (const card of msg.cards) {
      if (card.code === "AgentScopeRuntimeRequestCard") {
        // User message
        const input = card.data?.input;
        if (Array.isArray(input)) {
          for (const item of input) {
            const content = item?.content;
            if (Array.isArray(content)) {
              for (const c of content) {
                if (c?.type === "text" && c?.text) {
                  texts.push(c.text);
                }
              }
            } else if (typeof content === "string") {
              texts.push(content);
            }
          }
        }
      } else if (card.code === "AgentScopeRuntimeResponseCard") {
        // Assistant response
        const output = card.data?.output;
        if (Array.isArray(output)) {
          for (const item of output) {
            const content = item?.content;
            if (typeof content === "string") {
              texts.push(content);
            } else if (Array.isArray(content)) {
              for (const c of content) {
                if (c?.type === "text" && c?.text) {
                  texts.push(c.text);
                }
              }
            }
          }
        }
      }
    }
  }

  return texts.join("\n");
};

/** Get role label for message */
const getRoleLabel = (msg: IAgentScopeRuntimeWebUIMessage, t: (key: string) => string): string => {
  if (msg.role === "user") {
    return t("chat.search.userMessage");
  }
  return t("chat.search.assistantMessage");
};

interface SearchResult {
  messageId: string;
  role: string;
  roleLabel: string;
  text: string;
  matchedText: string;
}

const ChatSearchPanel: React.FC<ChatSearchPanelProps> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const [searchQuery, setSearchQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Get current session messages
  const currentSession = useMemo(() => {
    return sessions.find((s) => s.id === currentSessionId);
  }, [sessions, currentSessionId]);

  const messages = useMemo(() => {
    return currentSession?.messages || [];
  }, [currentSession]);

  // Search results
  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];

    const query = searchQuery.toLowerCase();
    const results: SearchResult[] = [];

    for (const msg of messages) {
      const text = extractMessageText(msg);
      if (text.toLowerCase().includes(query)) {
        // Find the matching portion
        const lowerText = text.toLowerCase();
        const matchIndex = lowerText.indexOf(query);
        const contextLength = 100;
        const start = Math.max(0, matchIndex - contextLength);
        const end = Math.min(text.length, matchIndex + searchQuery.length + contextLength);
        const matchedText = text.slice(start, end);

        results.push({
          messageId: msg.id || "",
          role: msg.role || "",
          roleLabel: getRoleLabel(msg, t),
          text,
          matchedText: start > 0 ? `...${matchedText}` : matchedText,
        });
      }
    }

    return results;
  }, [messages, searchQuery, t]);

  // Focus input when drawer opens
  useEffect(() => {
    if (open) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    } else {
      setSearchQuery("");
    }
  }, [open]);

  // Scroll to message (placeholder - would need integration with chat UI library)
  const handleResultClick = useCallback((result: SearchResult) => {
    // TODO: Implement scroll to message in chat
    // This would require integration with the @agentscope-ai/chat library
    // to scroll to the specific message
    console.log("Scroll to message:", result.messageId);
  }, []);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      width={360}
      closable={false}
      title={null}
      styles={{
        header: { display: "none" },
        body: {
          padding: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "hidden",
        },
        mask: { background: "transparent" },
      }}
      className={styles.drawer}
    >
      {/* Header bar */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.headerTitle}>{t("chat.search.title")}</span>
        </div>
        <div className={styles.headerRight}>
          <IconButton
            bordered={false}
            icon={<SparkOperateRightLine />}
            onClick={onClose}
          />
        </div>
      </div>

      {/* Search input */}
      <div className={styles.searchSection}>
        <Input
          ref={inputRef as any}
          placeholder={t("chat.search.placeholder")}
          prefix={<SparkSearchLine style={{ color: "rgba(0,0,0,0.25)" }} />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
          className={styles.searchInput}
        />
      </div>

      {/* Results count */}
      {searchQuery.trim() && (
        <div className={styles.resultsCount}>
          <Typography.Text type="secondary">
            {t("chat.search.resultsCount", { count: searchResults.length })}
          </Typography.Text>
        </div>
      )}

      {/* Results list */}
      <div className={styles.listWrapper}>
        <div className={styles.topGradient} />
        <div className={styles.list}>
          {searchQuery.trim() && searchResults.length === 0 ? (
            <Empty
              description={t("chat.search.noResults")}
              style={{ marginTop: 40 }}
            />
          ) : (
            <List
              dataSource={searchResults}
              renderItem={(item) => (
                <div
                  className={styles.searchResultItem}
                  onClick={() => handleResultClick(item)}
                >
                  <div className={styles.resultHeader}>
                    <span className={styles.resultRole}>{item.roleLabel}</span>
                  </div>
                  <div className={styles.resultContent}>
                    <Typography.Text
                      ellipsis
                      style={{ fontSize: 13 }}
                    >
                      {item.matchedText}
                    </Typography.Text>
                  </div>
                </div>
              )}
            />
          )}
        </div>
        <div className={styles.bottomGradient} />
      </div>
    </Drawer>
  );
};

export default ChatSearchPanel;