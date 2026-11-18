import type { ScalarTag, Tags } from "yaml";

// PyYAML SafeLoader's implicit scalar resolvers (used by ReMe's Markdown
// chunker). YAML 1.1 alone is insufficient: yaml also treats y/n as booleans,
// 08 as an integer, and 1e3 as a float, while SafeLoader keeps them as strings.
const integer: ScalarTag = {
  tag: "tag:yaml.org,2002:int",
  default: true,
  test: /^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$/,
  resolve(source) {
    const negative = source.startsWith("-");
    const value = source.replace(/^[-+]/, "").replace(/_/g, "");
    const result = value.includes(":")
      ? value.split(":").reduce((total, part) => total * 60n + BigInt(part), 0n)
      : /^0[0-7]+$/.test(value)
      ? BigInt(`0o${value}`)
      : BigInt(value);
    return negative ? -result : result;
  },
};

const float: ScalarTag = {
  tag: "tag:yaml.org,2002:float",
  default: true,
  test: /^(?:[-+]?[0-9][0-9_]*\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$/,
  // Only the scalar type matters here: memory tags exclude all floats.
  resolve: () => NaN,
};

const boolean: ScalarTag = {
  tag: "tag:yaml.org,2002:bool",
  default: true,
  test: /^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$/,
  resolve: (source) => /^(?:yes|true|on)$/i.test(source),
};

const timestamp: ScalarTag = {
  tag: "tag:yaml.org,2002:timestamp",
  default: true,
  test: /^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[Tt]|[ \t]+)[0-9]{1,2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9]{1,2}(?::[0-9]{2})?))?)$/,
  // Dates, like floats, are excluded from memory tags regardless of value.
  resolve: () => new Date(0),
};

/** Keep YAML collections/aliases, replacing only the differing scalar rules. */
export const memoryTagYamlScalars = (tags: Tags): Tags => [
  ...tags.filter(
    (tag) =>
      typeof tag === "string" ||
      ![integer.tag, float.tag, boolean.tag, timestamp.tag].includes(tag.tag),
  ),
  integer,
  float,
  boolean,
  timestamp,
];
