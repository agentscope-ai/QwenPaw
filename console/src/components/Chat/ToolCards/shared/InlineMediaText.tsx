/**
 * InlineMediaText — replace file references inside a plain-text tool result
 * with inline media previews.
 *
 * Used by GenericToolCard (scheme A): instead of appending previews below the
 * text, the matching link/path text is "cut out" and replaced by the preview
 * component. Any media that cannot be matched to a text span is still appended
 * at the end so that image-only MCP blocks are not lost.
 */

import React, { useMemo } from "react";
import type { MediaInfo } from "./utils";
import MediaPreview from "./MediaPreview";
import styles from "./toolCards.module.less";

export interface InlineMediaTextProps {
  text: string;
  media: MediaInfo[];
}

type Token =
  | { type: "text"; value: string }
  | { type: "media"; media: MediaInfo };

/** Build candidate literal strings that may appear in the result text. */
function buildMatchCandidates(
  rawUrl: string | undefined,
  name: string,
): string[] {
  const candidates = new Set<string>();
  if (rawUrl) {
    candidates.add(rawUrl);
    if (rawUrl.startsWith("file://")) {
      candidates.add(rawUrl.replace("file://", ""));
    }
    const rawBase = rawUrl.split("/").pop();
    if (rawBase) candidates.add(rawBase);
  }
  if (name) {
    candidates.add(name);
  }
  return Array.from(candidates).filter(Boolean);
}

/** Find the left-most, longest candidate match in the remaining text. */
function findBestMatch(
  text: string,
  mediaList: MediaInfo[],
  matched: Set<MediaInfo>,
): { index: number; length: number; media: MediaInfo } | null {
  let best: { index: number; length: number; media: MediaInfo } | null = null;

  for (const media of mediaList) {
    if (matched.has(media)) continue;
    const candidates = buildMatchCandidates(media.rawUrl, media.name);
    for (const candidate of candidates) {
      const idx = text.indexOf(candidate);
      if (idx === -1) continue;
      if (
        !best ||
        idx < best.index ||
        (idx === best.index && candidate.length > best.length)
      ) {
        best = { index: idx, length: candidate.length, media };
      }
    }
  }

  return best;
}

const InlineMediaText: React.FC<InlineMediaTextProps> = ({ text, media }) => {
  const tokens = useMemo<Token[]>(() => {
    const sortedMedia = [...media].sort(
      (a, b) => (b.rawUrl?.length ?? 0) - (a.rawUrl?.length ?? 0),
    );
    const matched = new Set<MediaInfo>();
    const result: Token[] = [];
    let remaining = text;

    while (remaining.length > 0) {
      const match = findBestMatch(remaining, sortedMedia, matched);
      if (!match) {
        result.push({ type: "text", value: remaining });
        break;
      }

      if (match.index > 0) {
        result.push({ type: "text", value: remaining.slice(0, match.index) });
      }
      result.push({ type: "media", media: match.media });
      matched.add(match.media);
      remaining = remaining.slice(match.index + match.length);
    }

    return result;
  }, [text, media]);

  const unmatched = useMemo(
    () =>
      media.filter(
        (m) => !tokens.some((t) => t.type === "media" && t.media === m),
      ),
    [media, tokens],
  );

  return (
    <div className={styles.inlineMediaText}>
      {tokens.map((token, index) =>
        token.type === "text" ? (
          <span key={`text-${index}`} className={styles.inlineMediaTextPlain}>
            {token.value}
          </span>
        ) : (
          <MediaPreview
            key={`media-${token.media.url}-${index}`}
            media={token.media}
          />
        ),
      )}
      {unmatched.length > 0 && (
        <div className={styles.inlineMediaTextUnmatched}>
          {unmatched.map((m) => (
            <MediaPreview key={`unmatched-${m.url}`} media={m} />
          ))}
        </div>
      )}
    </div>
  );
};

export default InlineMediaText;
