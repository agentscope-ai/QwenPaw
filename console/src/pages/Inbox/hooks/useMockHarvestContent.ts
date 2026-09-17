export interface MockMagazineItem {
  id: string;
  title: string;
  content: string;
  date: Date;
}

export function generateMockHistory(harvestName: string): MockMagazineItem[] {
  return Array.from({ length: 8 }, (_, index) => {
    const daysAgo = 7 - index;
    const date = new Date();
    date.setDate(date.getDate() - daysAgo);
    return {
      id: `${harvestName}-${index}`,
      title: `${harvestName} · #${index + 1}`,
      content:
        "This is a mock harvest content card used for the inbox demo viewer. " +
        "In the next phase, this will render real generated magazine/article output.",
      date,
    };
  });
}
