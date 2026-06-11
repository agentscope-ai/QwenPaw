import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface FilterBarProps {
  filterUserId: string;
  filterChannel: string;
  uniqueChannels: string[];
  onUserIdChange: (value: string) => void;
  onChannelChange: (value: string) => void;
}

export function FilterBar({
  filterUserId,
  filterChannel,
  uniqueChannels,
  onUserIdChange,
  onChannelChange,
}: FilterBarProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-2">
      <Input
        placeholder={t("sessions.filterUserId")}
        value={filterUserId}
        onChange={(e) => onUserIdChange(e.target.value)}
        className="w-[200px]"
      />
      <Select
        value={filterChannel || "all"}
        onValueChange={(value) => onChannelChange(value === "all" ? "" : value)}
      >
        <SelectTrigger className="w-[180px]">
          <SelectValue placeholder={t("sessions.filterChannel")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("sessions.filterChannel")}</SelectItem>
          {uniqueChannels.map((channel) => (
            <SelectItem key={channel} value={channel}>
              {channel}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
