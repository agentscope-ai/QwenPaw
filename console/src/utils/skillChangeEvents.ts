export interface SkillChangeDetail {
  agentId: string;
}

const SKILL_CHANGE_EVENT = "qwenpaw:skills-changed";

export function notifySkillChange(agentId: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<SkillChangeDetail>(SKILL_CHANGE_EVENT, {
      detail: { agentId },
    }),
  );
}

export function subscribeToSkillChanges(
  listener: (detail: SkillChangeDetail) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;

  const handleChange = (event: Event) => {
    listener((event as CustomEvent<SkillChangeDetail>).detail);
  };
  window.addEventListener(SKILL_CHANGE_EVENT, handleChange);
  return () => window.removeEventListener(SKILL_CHANGE_EVENT, handleChange);
}
