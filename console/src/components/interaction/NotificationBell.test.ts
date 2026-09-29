import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  join(process.cwd(), "src/components/interaction/NotificationBell.tsx"),
  "utf8",
);

describe("inbox notification icon", () => {
  it("uses an envelope while preserving the notification wrapper", () => {
    expect(source).toContain('import { Mail } from "lucide-react";');
    expect(source).toContain("<Mail size={19} strokeWidth={1.75} />");
    expect(source).not.toContain("<Bell");
    expect(source).toContain("count > 0 || attention");
  });
});
