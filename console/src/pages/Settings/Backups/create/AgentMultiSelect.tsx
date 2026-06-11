/**
 * Controlled multi-select for agent IDs used inside BackupScopeForm.
 * Injects a "__all__" sentinel as the first option to toggle all agents at once.
 */
import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, X } from "lucide-react";
import type { AgentSummary } from "@/api/types/agents";
import { Input } from "@/components/ui/input";

interface Props {
  agents: AgentSummary[];
  value: string[];
  onChange: (ids: string[]) => void;
}

export default function AgentMultiSelect({ agents, value, onChange }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const allSelected = agents.length > 0 && value.length === agents.length;

  const filtered = agents.filter((a) =>
    `${a.name} ${a.id}`.toLowerCase().includes(query.toLowerCase()),
  );

  const toggle = (id: string) => {
    onChange(
      value.includes(id) ? value.filter((v) => v !== id) : [...value, id],
    );
  };

  const toggleAll = () => {
    onChange(allSelected ? [] : agents.map((a) => a.id));
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selected = agents.filter((a) => value.includes(a.id));

  return (
    <div ref={containerRef} className="relative w-full">
      <button
        type="button"
        className="flex w-full min-h-9 items-center justify-between rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex flex-wrap gap-1">
          {selected.length === 0 ? (
            <span className="text-muted-foreground">
              {t("backup.agentsPlaceholder")}
            </span>
          ) : selected.length <= 3 ? (
            selected.map((a) => (
              <span
                key={a.id}
                className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-xs"
              >
                {a.name}
                <X
                  size={10}
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(a.id);
                  }}
                />
              </span>
            ))
          ) : (
            <span className="text-xs">
              {t("backup.agentsSelected", { count: selected.length })}
            </span>
          )}
        </div>
        <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-md">
          <div className="p-2">
            <Input
              placeholder={t("common.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-7 text-sm"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="max-h-64 overflow-y-auto">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent"
              onClick={toggleAll}
            >
              <Check
                size={14}
                className={allSelected ? "opacity-100" : "opacity-0"}
              />
              {allSelected ? t("backup.deselectAll") : t("backup.selectAll")}
            </button>
            {filtered.map((a) => (
              <button
                key={a.id}
                type="button"
                className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent"
                onClick={() => toggle(a.id)}
              >
                <Check
                  size={14}
                  className={value.includes(a.id) ? "opacity-100" : "opacity-0"}
                />
                {a.name}{" "}
                <span className="text-muted-foreground text-xs">({a.id})</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
