/**
 * Search bar that lives above the BackupTable.
 * Filtering is applied client-side in BackupTable via the searchQuery prop,
 * so this component is purely presentational (controlled input).
 */
import { Input } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import styles from "./BackupToolbar.module.less";

interface Props {
  searchQuery: string;
  onSearchChange: (q: string) => void;
}

export default function BackupToolbar({ searchQuery, onSearchChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className={styles.toolbar}>
      <Input
        className={styles.searchInput}
        prefix={<SearchOutlined />}
        placeholder={t("backup.searchPlaceholder")}
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
        allowClear
      />
    </div>
  );
}
