import React from "react";
import { useTranslation } from "react-i18next";
import { Input } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import styles from "./SessionPanel.module.less";

interface SessionSearchProps {
  value: string;
  onChange: (value: string) => void;
}

const SessionSearch: React.FC<SessionSearchProps> = ({ value, onChange }) => {
  const { t } = useTranslation();
  return (
    <div className={styles.searchContainer}>
      <Input
        prefix={<SearchOutlined />}
        placeholder={t("chat.sessionPanel.searchConversations")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        allowClear
        size="small"
        className={styles.searchInput}
      />
    </div>
  );
};

export default SessionSearch;
