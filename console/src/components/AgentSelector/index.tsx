import { useEffect, useState } from "react";
import {
  Bot,
  CheckCircle,
  EyeOff,
  ChevronRight,
  ChevronsUpDown,
} from "lucide-react";
import { useAgentStore } from "../../stores/agentStore";
import { agentsApi } from "../../api/modules/agents";
import { useTranslation } from "react-i18next";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import { useNavigate } from "react-router-dom";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface AgentSelectorProps {
  collapsed?: boolean;
}

export default function AgentSelector({
  collapsed = false,
}: AgentSelectorProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedAgent, agents, setSelectedAgent, setAgents } =
    useAgentStore();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    void loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoading(true);
      const data = await agentsApi.listAgents();
      const sortedAgents = [...data.agents].sort((a, b) => {
        if (a.enabled === b.enabled) return 0;
        return a.enabled ? -1 : 1;
      });
      setAgents(sortedAgents);
    } catch (error) {
      console.error("Failed to load agents:", error);
      message.error(t("agent.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (value: string) => {
    const targetAgent = agents?.find((a) => a.id === value);

    if (targetAgent && !targetAgent.enabled) {
      message.warning(t("agent.cannotSwitchToDisabled"));
      return;
    }

    setSelectedAgent(value);
    message.success(t("agent.switchSuccess"));
    setOpen(false);
  };

  // Auto-switch to default if selected agent was deleted or disabled
  useEffect(() => {
    if (!agents?.length || selectedAgent === "default") return;

    const currentAgent = agents.find((a) => a.id === selectedAgent);

    if (!currentAgent) {
      setSelectedAgent("default");
      message.warning(t("agent.currentAgentDeleted"));
    } else if (!currentAgent.enabled) {
      setSelectedAgent("default");
      message.warning(t("agent.currentAgentDisabled"));
    }
  }, [agents, selectedAgent, setSelectedAgent, t]);

  const enabledCount = agents?.filter((a) => a.enabled).length ?? 0;
  const currentAgentInfo = agents?.find((a) => a.id === selectedAgent);

  // Collapsed: show just the Bot icon with Tooltip
  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="w-10 h-10 flex items-center justify-center bg-accent border border-border rounded-lg text-foreground cursor-default mb-3 transition-all hover:bg-accent/80">
            <Bot size={18} strokeWidth={2} />
          </div>
        </TooltipTrigger>
        <TooltipContent side="right">
          {currentAgentInfo
            ? getAgentDisplayName(currentAgentInfo, t)
            : selectedAgent}
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 bg-card border border-border rounded-lg w-full transition-all mb-3">
      {/* Label row */}
      <div className="flex items-center justify-between text-[12px] font-medium text-muted-foreground select-none">
        <span>
          {t("agent.currentWorkspace")}
          {enabledCount > 0 && (
            <span className="text-muted-foreground"> ({enabledCount})</span>
          )}
        </span>
      </div>

      {/* Popover trigger */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            className="flex items-center gap-1.5 w-full bg-transparent border-none p-0 cursor-pointer text-left"
            aria-label={t("agent.selectAgent")}
          >
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              <Bot
                size={14}
                strokeWidth={2}
                className="text-foreground shrink-0"
              />
              <span className="font-semibold text-[13px] text-foreground/85 truncate">
                {currentAgentInfo
                  ? getAgentDisplayName(currentAgentInfo, t)
                  : selectedAgent}
              </span>
              {currentAgentInfo && !currentAgentInfo.enabled && (
                <EyeOff
                  size={12}
                  strokeWidth={2}
                  className="shrink-0 text-foreground/40"
                />
              )}
            </div>
            <ChevronsUpDown
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          </button>
        </PopoverTrigger>

        <PopoverContent
          className="w-[242px] p-0 rounded-xl border border-border shadow-aion"
          align="start"
          sideOffset={8}
        >
          {/* Dropdown header */}
          <div className="flex items-center justify-between px-3 pt-2 pb-1.5 border-b border-border mb-1">
            <span className="text-[12px] font-medium text-muted-foreground">
              {t("agent.currentWorkspace")}
            </span>
            <button
              className="flex items-center gap-0.5 text-[12px] font-medium text-foreground bg-none border-none p-0 cursor-pointer leading-none hover:text-foreground/80"
              onClick={() => {
                navigate("/agents");
                setOpen(false);
              }}
            >
              {t("agent.management")}
              <ChevronRight size={12} strokeWidth={2.5} />
            </button>
          </div>

          {/* Agent list */}
          <div className="py-1 px-1 max-h-60 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-4">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : (
              agents?.map((agent) => (
                <button
                  key={agent.id}
                  disabled={!agent.enabled}
                  className={cn(
                    "w-full text-left rounded-lg p-0 border-none bg-transparent cursor-pointer transition-all mb-0.5",
                    "hover:bg-accent",
                    !agent.enabled && "opacity-50 cursor-not-allowed",
                    agent.id === selectedAgent && "bg-accent",
                  )}
                  onClick={() => handleSelect(agent.id)}
                >
                  <div className="flex flex-col gap-1.5 px-3.5 py-2.5">
                    <div className="flex items-center gap-2.5">
                      {/* Agent icon */}
                      <div
                        className={cn(
                          "shrink-0 w-7 h-7 flex items-center justify-center rounded-lg transition-all",
                          "bg-secondary border border-border text-foreground",
                          agent.id === selectedAgent &&
                            "bg-primary border-transparent text-primary-foreground shadow-aion-sm",
                        )}
                      >
                        <Bot size={16} strokeWidth={2} />
                      </div>
                      {/* Agent info */}
                      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                        <div className="flex items-center justify-between gap-1.5 text-[13px] font-semibold text-foreground leading-[1.4]">
                          <span className="truncate">
                            {getAgentDisplayName(agent, t)}
                          </span>
                          <div className="flex items-center gap-1 shrink-0">
                            {agent.id === selectedAgent && (
                              <CheckCircle
                                size={14}
                                strokeWidth={2}
                                className="text-foreground animate-[fadeIn_0.3s_ease]"
                              />
                            )}
                            {!agent.enabled && (
                              <Badge
                                variant="outline"
                                className="text-[10px] px-1 py-0 h-4"
                              >
                                {t("agent.disabled")}
                              </Badge>
                            )}
                          </div>
                        </div>
                        {agent.description && (
                          <div className="text-[11px] text-muted-foreground truncate leading-[1.4]">
                            {agent.description}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="text-[10px] font-mono text-muted-foreground/60 tracking-[0.3px] pt-1 border-t border-border">
                      ID: {agent.id}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
