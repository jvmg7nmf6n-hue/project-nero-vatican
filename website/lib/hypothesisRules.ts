import type { AgentHypothesis, EveHypothesisRecord } from "./types";

// CC-1 directive, "every strategy page must show entry/exit rules and trade
// frequency": builds a hypothesis_name -> real structured rule lookup from
// BOTH Adam's (agent_hypotheses.json) and Eve's (eve_hypotheses.json) real
// committed files, so /factory-loop's Forward Trial table can show each
// hypothesis's real entry/exit rule regardless of which agent proposed it.
export interface HypothesisRules {
  structured_entry_rule: unknown;
  structured_exit_plan: unknown;
}

export function buildHypothesisRuleLookup(
  agentHypotheses: AgentHypothesis[],
  eveHypotheses: EveHypothesisRecord[]
): Map<string, HypothesisRules> {
  const lookup = new Map<string, HypothesisRules>();
  for (const h of agentHypotheses) {
    if (h.hypothesis_name) {
      lookup.set(h.hypothesis_name, { structured_entry_rule: h.structured_entry_rule, structured_exit_plan: h.structured_exit_plan });
    }
  }
  for (const h of eveHypotheses) {
    const name = h.raw_hypothesis?.hypothesis_name;
    if (name) {
      lookup.set(name, {
        structured_entry_rule: h.raw_hypothesis.structured_entry_rule,
        structured_exit_plan: h.raw_hypothesis.structured_exit_plan,
      });
    }
  }
  return lookup;
}
