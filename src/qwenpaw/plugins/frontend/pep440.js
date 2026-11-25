// The standalone checker uses the same PEP 440 ordering as packaging.version.
const pattern = new RegExp(
  [
    "^v?(?:(?<epoch>[0-9]+)!)?(?<release>[0-9]+(?:\\.[0-9]+)*)",
    "(?:[._-]?(?<pre>alpha|beta|preview|pre|rc|a|b|c)[._-]?(?<preNumber>[0-9]+)?)?",
    "(?<post>-(?<implicitPost>[0-9]+)|[._-]?(?:post|rev|r)[._-]?(?<postNumber>[0-9]+)?)?",
    "(?<dev>[._-]?dev[._-]?(?<devNumber>[0-9]+)?)?",
    "(?:\\+(?<local>[a-z0-9]+(?:[._-][a-z0-9]+)*))?$",
  ].join(""),
  "i",
);
const preOrder = {
  a: 1,
  alpha: 1,
  b: 2,
  beta: 2,
  c: 3,
  rc: 3,
  pre: 3,
  preview: 3,
};

export function parseVersion(value) {
  const trimmed = value.replace(
    /^[\p{White_Space}\u001c-\u001f]+|[\p{White_Space}\u001c-\u001f]+$/gu,
    "",
  );
  const parts = pattern.exec(trimmed)?.groups;
  if (!parts) throw new Error("sdk.version must be a valid PEP 440 version");

  const release = parts.release.split(".").map(BigInt);
  while (release.at(-1) === 0n) release.pop();
  let phase = 4;
  if (parts.pre) phase = preOrder[parts.pre.toLowerCase()];
  else if (parts.dev && !parts.post) phase = 0;

  return {
    epoch: BigInt(parts.epoch ?? 0),
    release,
    suffix: [
      phase,
      BigInt(parts.preNumber ?? 0),
      parts.post ? BigInt(parts.implicitPost ?? parts.postNumber ?? 0) : -1n,
      parts.dev ? BigInt(parts.devNumber ?? 0) : Infinity,
    ],
    local: (parts.local?.toLowerCase().split(/[._-]/) ?? []).map((segment) =>
      /^[0-9]+$/.test(segment) ? BigInt(segment) : segment,
    ),
  };
}

function compareValue(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function compareParts(left, right, compare = compareValue) {
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const difference = compare(left[i], right[i]);
    if (difference) return difference;
  }
  return compareValue(left.length, right.length);
}

function compareLocal(left, right) {
  if (typeof left === typeof right) return compareValue(left, right);
  return typeof left === "bigint" ? 1 : -1;
}

export function compareVersions(left, right) {
  return (
    compareValue(left.epoch, right.epoch) ||
    compareParts(left.release, right.release) ||
    compareParts(left.suffix, right.suffix) ||
    compareParts(left.local, right.local, compareLocal)
  );
}
