import React, { useState } from "react";
import { History, MessageSquarePlus, Search } from "lucide-react";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ChatSessionDrawer from "../ChatSessionDrawer";
import ChatSearchPanel from "../ChatSearchPanel";
import PlanPanel from "../../../../components/PlanPanel";

const PlanIcon = () => (
  <svg
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);

const PINNED_STORAGE_KEY = "qwenpaw_history_drawer_pinned";

interface ChatActionGroupProps {
  planEnabled?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  planEnabled = false,
}) => {
  const { t } = useTranslation();

  const [historyPinned, setHistoryPinned] = useState(() => {
    try {
      return localStorage.getItem(PINNED_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  // If pinned, auto-open drawer on mount
  const [historyOpen, setHistoryOpen] = useState(historyPinned);

  const handlePinChange = (pinned: boolean) => {
    setHistoryPinned(pinned);
    try {
      if (pinned) {
        localStorage.setItem(PINNED_STORAGE_KEY, "true");
      } else {
        localStorage.removeItem(PINNED_STORAGE_KEY);
      }
    } catch {
      // storage full or unavailable
    }
  };

  const [searchOpen, setSearchOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const { createSession } = useChatAnywhereSessions();

  const iconBtnClass =
    "inline-flex items-center justify-center rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors";

  return (
    <div className="flex items-center gap-2">
      {planEnabled && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className={iconBtnClass}
              onClick={() => setPlanOpen(true)}
            >
              <PlanIcon />
            </button>
          </TooltipTrigger>
          <TooltipContent>{t("plan.title", "Plan")}</TooltipContent>
        </Tooltip>
      )}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={iconBtnClass}
            onClick={() => createSession()}
          >
            <MessageSquarePlus size={16} />
          </button>
        </TooltipTrigger>
        <TooltipContent>{t("chat.newChatTooltip")}</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={iconBtnClass}
            onClick={() => setSearchOpen(true)}
          >
            <Search size={16} />
          </button>
        </TooltipTrigger>
        <TooltipContent>{t("chat.searchTooltip")}</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={iconBtnClass}
            onClick={() => setHistoryOpen(true)}
          >
            <History size={16} />
          </button>
        </TooltipTrigger>
        <TooltipContent>{t("chat.chatHistoryTooltip")}</TooltipContent>
      </Tooltip>
      <ChatSessionDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        pinned={historyPinned}
        onPinChange={handlePinChange}
      />
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
      {planEnabled && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
    </div>
  );
};

export default ChatActionGroup;
