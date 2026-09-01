import { useCallback } from "react";
import { Drawer } from "antd";
import { useNavigate } from "react-router-dom";

import SidebarSessionList from "../../../../layouts/SidebarSessionList";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import { buildChatPath } from "../../../../utils/sessionRoute";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import sessionApi from "../../sessionApi";

interface ChatSessionDrawerProps {
  open: boolean;
  onClose: () => void;
}

/** Mobile shell for the shared sidebar conversation-history component. */
export default function ChatSessionDrawer({
  open,
  onClose,
}: ChatSessionDrawerProps) {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const createNewSession = useCreateNewSession();

  const handleNewChat = useCallback(() => {
    void (async () => {
      try {
        await createNewSession();
      } catch {
        // Session creation reports user-facing errors through its own hook.
      } finally {
        onClose();
      }
    })();
  }, [createNewSession, onClose]);

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      const effectiveId = sessionApi.getEffectiveSessionId(sessionId);
      navigate(buildChatPath(effectiveId));
      onClose();
    },
    [navigate, onClose],
  );

  return (
    <Drawer
      open={open}
      onClose={onClose}
      destroyOnHidden
      placement="right"
      width={isMobile ? "calc(100vw - 56px)" : 330}
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
          background: "var(--colorBgContainer, #f9f8f4)",
        },
        mask: { background: "transparent" },
      }}
    >
      <SidebarSessionList
        onNewChat={handleNewChat}
        onSessionClick={handleSessionClick}
        onClose={onClose}
      />
    </Drawer>
  );
}
