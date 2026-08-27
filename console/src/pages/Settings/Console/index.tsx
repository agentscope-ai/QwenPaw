import { Card } from "antd";
import { MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import sessionApi from "@/pages/Chat/sessionApi";
import HistoryPageSizeInput from "@/pages/Chat/components/HistoryPageSizeInput";

export default function ConsoleSettingsPage() {
  const { t } = useTranslation();

  return (
    <div style={{ padding: "0 4px 24px" }}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.console", "Console")}
      />
      <Card
        title={
          <span
            style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
          >
            <MessageSquare size={18} />
            {t("consoleSettings.chatSection", "Chat")}
          </span>
        }
      >
        <HistoryPageSizeInput
          onCommitted={() => {
            void sessionApi.reloadAfterPageSizeChange();
          }}
        />
      </Card>
    </div>
  );
}
