import { useRuleIntegrity } from "../hooks/useRuleIntegrity";
import { RuleIntegrityRepairBanner } from "./RuleIntegrityRepairBanner";

/** Global tamper/repair banner — mounted once in MainLayout below Header. */
export function GlobalRuleIntegrityRepairBanner() {
  const { rulesIntegrity } = useRuleIntegrity();

  return (
    <RuleIntegrityRepairBanner rulesIntegrity={rulesIntegrity} layout="global" />
  );
}
