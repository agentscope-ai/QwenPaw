import type { HistoryUserMessage } from "./historyMessageWindowStore";

type Page = { items: HistoryUserMessage[]; before?: string };
export class InputMessageRecall {
  private page?: Page;
  private position = 0;
  private cursor?: string;
  private newer: (string | undefined)[] = [];
  private texts = new Map<string, string>();
  private loadPage: (before?: string) => Promise<Page>;
  private loadText: (id: string) => Promise<string>;
  private fallback: string[];

  constructor(
    loadPage: (before?: string) => Promise<Page>,
    loadText: (id: string) => Promise<string>,
    fallback: string[] = [],
  ) {
    this.loadPage = loadPage;
    this.loadText = loadText;
    this.fallback = fallback;
  }

  /** undefined means the oldest boundary; null restores the unsent draft. */
  async move(older: boolean): Promise<string | null | undefined> {
    if (!this.page) {
      if (!older) return undefined;
      this.page = await this.loadPage();
      if (!this.page.items.length && this.fallback.length) {
        this.page = {
          items: this.fallback.map((text, i) => {
            const id = `local:${i}`;
            this.texts.set(id, text);
            return { messageId: id, preview: "", anchor: "", createdAt: "" };
          }),
        };
      }
      this.position = this.page.items.length;
    }
    // Skip attachment-only inputs without fetching assistant history.
    for (let steps = 0; steps < 100; steps++) {
      let next = this.position + (older ? -1 : 1);
      if (older && next < 0) {
        if (!this.page.before) return undefined;
        const cursor = this.page.before;
        const page = await this.loadPage(cursor);
        if (!page.items.length || page.before === cursor) return undefined;
        this.newer.push(this.cursor);
        this.cursor = cursor;
        this.page = page;
        this.position = page.items.length;
        next = page.items.length - 1;
      } else if (!older && next >= this.page.items.length) {
        if (!this.newer.length) {
          this.position = this.page.items.length;
          return null;
        }
        const cursor = this.newer[this.newer.length - 1];
        const page = await this.loadPage(cursor);
        this.newer.pop();
        this.cursor = cursor;
        this.page = page;
        this.position = -1;
        next = 0;
      }
      const item = this.page.items[next];
      if (!item) return undefined;
      let text = this.texts.get(item.messageId);
      if (text === undefined) {
        text = await this.loadText(item.messageId);
        this.texts.set(item.messageId, text);
        if (this.texts.size > 20)
          this.texts.delete(this.texts.keys().next().value!);
      }
      this.position = next;
      if (text.trim()) return text;
    }
    return undefined;
  }
}
