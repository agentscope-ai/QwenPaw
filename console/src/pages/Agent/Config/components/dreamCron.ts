export function isValidDreamCronShape(value?: string) {
  if (!value?.trim()) {
    return false;
  }
  const fields = value.trim().split(/\s+/);
  if (
    fields.length !== 5 ||
    !fields.every((field) => /^[a-z0-9*/,-]+$/i.test(field))
  ) {
    return false;
  }

  // Catch numeric values outside the ranges accepted by APScheduler before
  // submitting the form. The backend remains authoritative for the complete
  // cron grammar (named months/weekdays, ranges, lists, and steps).
  const numericRanges = [
    [0, 59],
    [0, 23],
    [1, 31],
    [1, 12],
    [0, 6],
  ] as const;
  return fields.every((field, index) => {
    const [minimum, maximum] = numericRanges[index];
    return [...field.matchAll(/\d+/g)].every(({ 0: token }) => {
      const number = Number(token);
      return number >= minimum && number <= maximum;
    });
  });
}
