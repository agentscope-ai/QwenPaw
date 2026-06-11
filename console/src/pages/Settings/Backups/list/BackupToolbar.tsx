/**
 * Search bar that lives above the BackupTable.
 */
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import styles from "./BackupToolbar.module.less";

interface Props {
  searchQuery: string;
  onSearchChange: (q: string) => void;
}

export default function BackupToolbar({ searchQuery, onSearchChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className={styles.toolbar}>
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
        <Input
          className={`${styles.searchInput} pl-8`}
          placeholder={t("backup.searchPlaceholder")}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
    </div>
  );
}
