import type { PersonalLibraryDocument } from "../../api/modules/personalLibrary";

const PERSONAL_LIBRARY_MENTION_PATTERN =
  /@\[((?:\\.|[^\]])+)\]\(personal-library:([A-Za-z0-9-]+)\)/g;

function escapeMentionLabel(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/\]/g, "\\]");
}

function unescapeMentionLabel(value: string): string {
  return value.replace(/\\([\\\]])/g, "$1");
}

export function encodePersonalLibraryMention(
  document: Pick<PersonalLibraryDocument, "id" | "name">,
): string {
  return `@[${escapeMentionLabel(document.name)}](personal-library:${document.id})`;
}

export function findPersonalLibraryMentionToken(value: string, cursor: number) {
  const beforeCursor = value.slice(0, cursor);
  const match = /(^|\s)@([^\s@]*)$/.exec(beforeCursor);
  if (!match) return null;
  return {
    keyword: match[2].toLowerCase(),
    mentionStart: cursor - match[2].length - 1,
    cursor,
  };
}

function rewriteText(value: string, documentIds: Set<string>): string {
  return value.replace(
    PERSONAL_LIBRARY_MENTION_PATTERN,
    (_raw, encodedName: string, documentId: string) => {
      documentIds.add(documentId);
      return `@${unescapeMentionLabel(encodedName)}`;
    },
  );
}

export function rewritePersonalLibraryMentionsInInput(
  input: Array<Record<string, unknown>>,
) {
  const documentIds = new Set<string>();
  const rewritten = input.map((message) => {
    if (message.role !== "user") return message;
    if (typeof message.content === "string") {
      return { ...message, content: rewriteText(message.content, documentIds) };
    }
    if (!Array.isArray(message.content)) return message;
    return {
      ...message,
      content: message.content.map((part) => {
        if (
          !part ||
          typeof part !== "object" ||
          (part as Record<string, unknown>).type !== "text" ||
          typeof (part as Record<string, unknown>).text !== "string"
        ) {
          return part;
        }
        return {
          ...(part as Record<string, unknown>),
          text: rewriteText(
            (part as Record<string, unknown>).text as string,
            documentIds,
          ),
        };
      }),
    };
  });
  return { input: rewritten, documentIds: [...documentIds].slice(0, 5) };
}

export function selectedDocumentIdsPresentInInput(
  input: Array<Record<string, unknown>>,
  selected: Array<Pick<PersonalLibraryDocument, "id" | "name">>,
): string[] {
  const text = input
    .filter((message) => message.role === "user")
    .flatMap((message) =>
      typeof message.content === "string"
        ? [message.content]
        : Array.isArray(message.content)
          ? message.content
              .filter(
                (part) =>
                  part &&
                  typeof part === "object" &&
                  (part as Record<string, unknown>).type === "text" &&
                  typeof (part as Record<string, unknown>).text === "string",
              )
              .map((part) => (part as Record<string, unknown>).text as string)
          : [],
    )
    .join("\n");
  return selected
    .filter((document) => text.includes(`@${document.name}`))
    .map((document) => document.id)
    .slice(0, 5);
}
