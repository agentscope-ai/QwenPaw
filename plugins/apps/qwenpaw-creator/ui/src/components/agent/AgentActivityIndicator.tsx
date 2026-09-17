export type AgentActivityPhase =
  | "running"
  | "completed"
  | "attention"
  | "waiting"
  | "idle";

/** Decorative only: the adjacent public label carries the accessible status. */
export default function AgentActivityIndicator({
  phase,
}: {
  phase: AgentActivityPhase;
}) {
  return (
    <span
      className="agent-activity-indicator"
      data-phase={phase}
      aria-hidden="true"
    >
      <span />
      <span />
      <span />
    </span>
  );
}
