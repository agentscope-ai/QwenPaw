/** QwenPaw console stores UI language in ``localStorage.language``. */

const LANGUAGE_KEY = "language";
const LANGUAGE_EVENT = "qwenpaw-pet-language-change";

export function readConsoleLanguage(): string {
  try {
    return localStorage.getItem(LANGUAGE_KEY) || "";
  } catch {
    return "";
  }
}

/** Detect same-tab writes — ``storage`` only fires across tabs. */
function installLanguageSetItemHook(): void {
  const marker = "__qwenpawPetLanguageHook";
  const proto = Storage.prototype as Storage & Record<string, unknown>;
  if (proto[marker]) return;

  const nativeSetItem = proto.setItem;
  proto.setItem = function (key: string, value: string) {
    nativeSetItem.call(this, key, value);
    if (key === LANGUAGE_KEY) {
      window.dispatchEvent(new CustomEvent(LANGUAGE_EVENT, { detail: value }));
    }
  };
  proto[marker] = true;
}

/** Subscribe to QwenPaw header language switcher (no console changes needed). */
export function subscribeConsoleLanguage(
  fn: (language: string) => void,
): () => void {
  installLanguageSetItemHook();

  let last = readConsoleLanguage();
  const emit = (language: string) => {
    if (language === last) return;
    last = language;
    fn(language);
  };

  const onCustom = (event: Event) => {
    emit(String((event as CustomEvent<string>).detail ?? ""));
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === LANGUAGE_KEY) emit(event.newValue ?? "");
  };

  window.addEventListener(LANGUAGE_EVENT, onCustom);
  window.addEventListener("storage", onStorage);

  const timer = window.setInterval(() => {
    emit(readConsoleLanguage());
  }, 500);

  return () => {
    window.removeEventListener(LANGUAGE_EVENT, onCustom);
    window.removeEventListener("storage", onStorage);
    window.clearInterval(timer);
  };
}
