interface RequestContentItem {
  type: string;
  status?: unknown;
  text?: string;
  image_url?: string;
  video_url?: string;
  video_poster?: string;
  audio_url?: string;
  data?: string;
  file_url?: string;
  file_name?: string;
  fileName?: string;
  file_size?: number;
}

type RequestContent = RequestContentItem[];

export interface RuntimeRequest {
  input: Array<{
    content?: RequestContent;
  }>;
}

interface RequestCard {
  code: string;
  data: unknown;
}

const CONTENT_TEXT = "text";
const CONTENT_IMAGE = "image";
const CONTENT_VIDEO = "video";
const CONTENT_AUDIO = "audio";
const CONTENT_FILE = "file";

function appendGroupedCard(
  cards: RequestCard[],
  code: string,
  item: Record<string, unknown>,
) {
  const existing = cards.find((card) => card.code === code);
  if (existing && Array.isArray(existing.data)) {
    existing.data.push(item);
    return;
  }

  cards.push({ code, data: [item] });
}

export function requestContentToCards(content: RequestContent): RequestCard[] {
  return content.reduce<RequestCard[]>((cards, item) => {
    if (item.type === CONTENT_TEXT) {
      cards.push({
        code: "Text",
        data: {
          content: item.text,
        },
      });
    }

    if (item.type === CONTENT_IMAGE) {
      appendGroupedCard(cards, "Images", { url: item.image_url });
    }

    if (item.type === CONTENT_VIDEO) {
      appendGroupedCard(cards, "Videos", {
        src: item.video_url,
        poster: item.video_poster,
      });
    }

    if (item.type === CONTENT_AUDIO) {
      appendGroupedCard(cards, "Audios", {
        src: item.audio_url || item.data,
      });
    }

    if (item.type === CONTENT_FILE) {
      appendGroupedCard(cards, "Files", {
        url: item.file_url,
        name: item.file_name || item.fileName,
        size: item.file_size,
      });
    }

    return cards;
  }, []);
}
