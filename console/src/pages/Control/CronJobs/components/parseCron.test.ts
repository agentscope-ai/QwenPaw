import { describe, it, expect } from "vitest";
import { parseCron, serializeCron } from "./parseCron";

describe("parseCron", () => {
  it("empty string defaults to daily at 09:00", () => {
    expect(parseCron("")).toEqual({ type: "daily", hour: 9, minute: 0 });
  });

  it('"0 * * * *" parses as hourly', () => {
    expect(parseCron("0 * * * *")).toEqual({ type: "hourly", minute: 0 });
  });

  it('"0 9 * * *" parses as daily at 09:00', () => {
    expect(parseCron("0 9 * * *")).toEqual({
      type: "daily",
      hour: 9,
      minute: 0,
    });
  });

  it('"30 14 * * *" parses as daily at 14:30', () => {
    expect(parseCron("30 14 * * *")).toEqual({
      type: "daily",
      hour: 14,
      minute: 30,
    });
  });

  it('"0 9 * * mon,wed,fri" parses as weekly with named days', () => {
    expect(parseCron("0 9 * * mon,wed,fri")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed", "fri"],
    });
  });

  it('"*/15 * * * *" parses as a visual interval', () => {
    expect(parseCron("*/15 * * * *")).toEqual({
      type: "minutes",
      intervalMinutes: 15,
    });
  });

  it('"0 9 * * 1,3,5" converts numeric days to named abbreviations', () => {
    const result = parseCron("0 9 * * 1,3,5");
    expect(result.type).toBe("weekly");
    expect(result.daysOfWeek).toEqual(["mon", "wed", "fri"]);
  });
});

describe("serializeCron", () => {
  it("hourly type serializes to '0 * * * *'", () => {
    expect(serializeCron({ type: "hourly" })).toBe("0 * * * *");
  });

  it("daily type with hour and minute serializes correctly", () => {
    expect(serializeCron({ type: "daily", hour: 9, minute: 30 })).toBe(
      "30 9 * * *",
    );
  });

  it("custom type preserves rawCron verbatim", () => {
    expect(serializeCron({ type: "custom", rawCron: "*/15 * * * *" })).toBe(
      "*/15 * * * *",
    );
  });
});

describe("visual schedule round trips", () => {
  it.each(["* * * * *", "*/5 * * * *", "0 9 1 * *", "30 18 31 * *"])(
    "preserves %s",
    (cron) => {
      expect(serializeCron(parseCron(cron))).toBe(cron);
    },
  );
  it.each(["*/25 * * * *", "0 9 L * *", "0 9 1,15 * *", "0 9 * 2 *"])(
    "keeps unsupported %s in advanced mode",
    (cron) => {
      expect(parseCron(cron)).toEqual({ type: "custom", rawCron: cron });
      expect(serializeCron(parseCron(cron))).toBe(cron);
    },
  );
});

// ---------------------------------------------------------------------------
// Appended coverage batch: malformed expressions, day-of-week range parsing
// and the serializeCron fallbacks. Every case below pins observable output of
// the two exported pure functions; none asserts internal state.
// ---------------------------------------------------------------------------

type SerializeArg = Parameters<typeof serializeCron>[0];

describe("parseCron — expression shape validation", () => {
  it("whitespace-only input falls back to daily at 09:00", () => {
    expect(parseCron("   ")).toEqual({ type: "daily", hour: 9, minute: 0 });
  });

  it("null-ish input falls back to daily at 09:00 instead of throwing", () => {
    expect(parseCron(undefined as unknown as string)).toEqual({
      type: "daily",
      hour: 9,
      minute: 0,
    });
  });

  it("surrounding whitespace is trimmed before parsing", () => {
    expect(parseCron("  30 14 * * *  ")).toEqual({
      type: "daily",
      hour: 14,
      minute: 30,
    });
  });

  it.each([
    ["four fields only", "0 9 * *"],
    ["six fields (seconds form)", "0 0 9 * * *"],
    ["prose schedule", "every day at nine"],
    ["single token", "*"],
  ])(
    "non five-field expression (%s) becomes custom with rawCron kept",
    (_label, cron) => {
      expect(parseCron(cron)).toEqual({ type: "custom", rawCron: cron });
    },
  );

  it.each([
    ["minute above 59", "70 9 * * *"],
    ["hour above 23", "0 25 * * *"],
    ["non-numeric minute", "ab 9 * * *"],
    ["non-numeric hour", "0 cd * * *"],
  ])("out-of-range plain number (%s) degrades to custom", (_label, cron) => {
    expect(parseCron(cron)).toEqual({ type: "custom", rawCron: cron });
  });

  it("minute 59 and hour 23 are accepted as the inclusive upper bounds", () => {
    expect(parseCron("59 23 * * *")).toEqual({
      type: "daily",
      hour: 23,
      minute: 59,
    });
  });

  it("midnight daily keeps hour and minute zero", () => {
    expect(parseCron("0 0 * * *")).toEqual({
      type: "daily",
      hour: 0,
      minute: 0,
    });
  });
});

describe("parseCron — weekly day-of-week tokens", () => {
  it("named range expands to every day it spans", () => {
    expect(parseCron("0 9 * * mon-wed")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "tue", "wed"],
    });
  });

  it("numeric range expands using the crontab numbering", () => {
    expect(parseCron("0 9 * * 1-5")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "tue", "wed", "thu", "fri"],
    });
  });

  it("mixed range expands across both endpoints", () => {
    expect(parseCron("15 8 * * 6-sun")).toEqual({
      type: "weekly",
      hour: 8,
      minute: 15,
      daysOfWeek: ["sat", "sun"],
    });
  });

  it("whole week range yields all seven days in canonical order", () => {
    expect(parseCron("0 9 * * mon-sun").daysOfWeek).toEqual([
      "mon",
      "tue",
      "wed",
      "thu",
      "fri",
      "sat",
      "sun",
    ]);
  });

  it("uppercase tokens are normalised to lower case", () => {
    expect(parseCron("0 9 * * MON,WED")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed"],
    });
  });

  it("day tokens separated by spaces break the five field shape", () => {
    // CRON_RE accepts exactly five whitespace separated fields, so a padded
    // list never reaches the per-token trimming logic and stays raw.
    expect(parseCron("0 9 * * mon , wed")).toEqual({
      type: "custom",
      rawCron: "0 9 * * mon , wed",
    });
  });

  it("repeated named token is deduplicated", () => {
    expect(parseCron("0 9 * * mon,mon,wed")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed"],
    });
  });

  it("repeated numeric token is deduplicated", () => {
    expect(parseCron("0 9 * * 1,1,3")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed"],
    });
  });

  it("overlapping ranges do not duplicate the shared days", () => {
    expect(parseCron("0 9 * * mon-wed,tue-fri")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "tue", "wed", "thu", "fri"],
    });
  });

  it("numeric 0 and its alias 7 both mean sunday", () => {
    expect(parseCron("0 9 * * 0").daysOfWeek).toEqual(["sun"]);
    expect(parseCron("0 9 * * 7").daysOfWeek).toEqual(["sun"]);
  });

  it("a single named day stays weekly", () => {
    expect(parseCron("0 9 * * sat")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["sat"],
    });
  });

  it.each([
    ["empty token in list", "0 9 * * mon,,fri"],
    ["trailing comma", "0 9 * * mon,"],
    ["three-part range", "0 9 * * mon-wed-fri"],
    ["range with empty start", "0 9 * * -wed"],
    ["range with empty end", "0 9 * * mon-"],
    ["unknown names in range", "0 9 * * xyz-abc"],
    ["reversed range", "0 9 * * fri-mon"],
    ["unknown single token", "0 9 * * 9"],
    ["unknown name token", "0 9 * * notaday"],
    ["partially unknown list", "0 9 * * mon,zzz"],
  ])(
    "lossy day-of-week (%s) degrades the whole expression to custom",
    (_label, cron) => {
      // Losing the day set silently would schedule the job on every day, so the
      // parser refuses to guess and hands the raw expression back to the caller.
      expect(parseCron(cron)).toEqual({ type: "custom", rawCron: cron });
    },
  );

  it("weekly shape with an unusable day field never reports type weekly", () => {
    const result = parseCron("0 9 * * mon-wed-fri");
    expect(result.type).not.toBe("weekly");
    expect(result.daysOfWeek).toBeUndefined();
  });
});

describe("serializeCron — defaults and fallbacks", () => {
  it("daily without explicit time defaults to 09:00", () => {
    expect(serializeCron({ type: "daily" })).toBe("0 9 * * *");
  });

  it("weekly without explicit time defaults to 09:00 on monday", () => {
    expect(serializeCron({ type: "weekly" })).toBe("0 9 * * mon");
  });

  it("weekly with an empty day list defaults to monday", () => {
    expect(
      serializeCron({ type: "weekly", hour: 10, minute: 5, daysOfWeek: [] }),
    ).toBe("5 10 * * mon");
  });

  it("weekly with only unrecognised days defaults to monday", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 9,
        minute: 0,
        daysOfWeek: ["nope"],
      }),
    ).toBe("0 9 * * mon");
  });

  it("custom without rawCron falls back to the daily default", () => {
    expect(serializeCron({ type: "custom" })).toBe("0 9 * * *");
  });

  it("custom with an empty rawCron falls back to the daily default", () => {
    expect(serializeCron({ type: "custom", rawCron: "" })).toBe("0 9 * * *");
  });

  it("an unknown schedule type still yields the daily default", () => {
    expect(
      serializeCron({ type: "not-a-type" } as unknown as SerializeArg),
    ).toBe("0 9 * * *");
  });
});

describe("serializeCron — day list rendering", () => {
  it("contiguous days collapse into a single range", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 9,
        minute: 0,
        daysOfWeek: ["mon", "tue", "wed"],
      }),
    ).toBe("0 9 * * mon-wed");
  });

  it("a full work week collapses into one range", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 7,
        minute: 30,
        daysOfWeek: ["mon", "tue", "wed", "thu", "fri"],
      }),
    ).toBe("30 7 * * mon-fri");
  });

  it("non-contiguous days are listed separately", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 9,
        minute: 0,
        daysOfWeek: ["mon", "wed"],
      }),
    ).toBe("0 9 * * mon,wed");
  });

  it("two runs of contiguous days become two range segments", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 9,
        minute: 0,
        daysOfWeek: ["mon", "tue", "thu", "fri"],
      }),
    ).toBe("0 9 * * mon-tue,thu-fri");
  });

  it("input order does not affect the emitted canonical order", () => {
    const forward = serializeCron({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["wed", "mon"],
    });
    const backward = serializeCron({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed"],
    });
    expect(forward).toBe("0 9 * * mon,wed");
    expect(backward).toBe(forward);
  });

  it("unrecognised entries are dropped while valid ones survive", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 9,
        minute: 0,
        daysOfWeek: ["mon", "garbage", "fri"],
      }),
    ).toBe("0 9 * * mon,fri");
  });

  it("a lone sunday serialises to sun", () => {
    expect(
      serializeCron({
        type: "weekly",
        hour: 0,
        minute: 0,
        daysOfWeek: ["sun"],
      }),
    ).toBe("0 0 * * sun");
  });

  it("single-digit hour and minute are not zero padded", () => {
    expect(serializeCron({ type: "daily", hour: 5, minute: 3 })).toBe(
      "3 5 * * *",
    );
  });
});

describe("parseCron / serializeCron round trip", () => {
  it.each([
    { type: "hourly", minute: 0 },
    { type: "daily", hour: 9, minute: 0 },
    { type: "daily", hour: 23, minute: 59 },
    { type: "weekly", hour: 9, minute: 0, daysOfWeek: ["mon", "wed", "fri"] },
    { type: "weekly", hour: 8, minute: 15, daysOfWeek: ["mon", "tue", "wed"] },
    { type: "minutes", intervalMinutes: 15 },
    { type: "custom", rawCron: "*/25 * * * *" },
  ] as SerializeArg[])(
    "serialize then parse returns the same parts",
    (parts) => {
      const cron = serializeCron(parts);
      expect(parseCron(cron)).toEqual(parts);
    },
  );

  it("numeric day input round trips to the named form", () => {
    const parsed = parseCron("0 9 * * 1-5");
    expect(serializeCron(parsed)).toBe("0 9 * * mon-fri");
    expect(parseCron(serializeCron(parsed))).toEqual(parsed);
  });
});
