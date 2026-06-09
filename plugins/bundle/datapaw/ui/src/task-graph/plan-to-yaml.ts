import type { PlanSnapshot } from "./types";

function formatYamlValue(value: string): string {
  if (/[:#\[\]{}|>&*!%@`]/.test(value) || value.trim() !== value) {
    return `"${value.replace(/"/g, '\\"')}"`;
  }
  return value;
}

/** Serialize plan snapshot to editable YAML (matches frontend structure). */
export function planToEditableYaml(plan: PlanSnapshot): string {
  const lines: string[] = [];

  lines.push(`name: ${formatYamlValue(plan.name)}`);

  if (plan.description) {
    lines.push(`description: ${formatYamlValue(plan.description)}`);
  }

  if (plan.expected_outcome) {
    lines.push(`expected_outcome: ${formatYamlValue(plan.expected_outcome)}`);
  }

  lines.push("nodes:");

  Object.values(plan.nodes).forEach((node) => {
    lines.push(`  - node_id: ${node.node_id}`);
    if (node.name) {
      lines.push(`    name: ${formatYamlValue(node.name)}`);
    }
    if (node.description) {
      lines.push(`    description: ${formatYamlValue(node.description)}`);
    }
    if (node.expected_outcome) {
      lines.push(
        `    expected_outcome: ${formatYamlValue(node.expected_outcome)}`,
      );
    }

    const deps = node.deps ?? [];
    if (deps.length === 0) {
      lines.push("    deps: []");
    } else {
      lines.push("    deps:");
      deps.forEach((dep) => {
        lines.push(`      - ${dep}`);
      });
    }
  });

  return `${lines.join("\n")}\n`;
}
