import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Popover, Tooltip } from "antd";
import { Smile } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CUSTOM_EMOJI_URLS } from "./customEmoji";
import styles from "./index.module.less";

interface EmojiItem {
  /** Escaped sequences keep emoji chars safe through editing/transport. */
  e: string;
  zh: string;
  en: string;
  /** Custom emoji image url; token form is [emoji:<url>]. */
  src?: string;
}

// Grouped like agentscope-platform-front: faces → animals → gestures →
// hearts → plants & food → celebration & symbols.
const EMOJIS: EmojiItem[] = [
  { e: "\u{1F600}", zh: "咧嘴笑", en: "Grinning face" },
  { e: "\u{1F603}", zh: "大笑", en: "Grinning face with big eyes" },
  { e: "\u{1F604}", zh: "欢笑", en: "Grinning face with smiling eyes" },
  { e: "\u{1F601}", zh: "呲牙", en: "Beaming face" },
  { e: "\u{1F606}", zh: "眯眼笑", en: "Grinning squinting face" },
  { e: "\u{1F605}", zh: "尴尬笑", en: "Grinning face with sweat" },
  { e: "\u{1F923}", zh: "笑得打滚", en: "Rolling on the floor laughing" },
  { e: "\u{1F602}", zh: "笑哭", en: "Face with tears of joy" },
  { e: "\u{1F642}", zh: "微笑", en: "Slightly smiling face" },
  { e: "\u{1F643}", zh: "倒脸", en: "Upside-down face" },
  { e: "\u{1F609}", zh: "眨眼", en: "Winking face" },
  { e: "\u{1F60A}", zh: "害羞笑", en: "Blushing smile" },
  { e: "\u{1F607}", zh: "天使光环", en: "Smile with halo" },
  { e: "\u{1F970}", zh: "幸福笑脸", en: "Smiling face with hearts" },
  { e: "\u{1F60D}", zh: "花痴眼", en: "Heart-eyes" },
  { e: "\u{1F929}", zh: "星星眼", en: "Star-struck" },
  { e: "\u{1F618}", zh: "飞吻", en: "Blowing a kiss" },
  { e: "\u{1F617}", zh: "亲吻", en: "Kissing face" },
  { e: "\u{1F61A}", zh: "闭眼亲", en: "Kissing with closed eyes" },
  { e: "\u{1F619}", zh: "微笑亲", en: "Kissing with smiling eyes" },
  { e: "\u{1F60B}", zh: "好吃", en: "Face savoring food" },
  { e: "\u{1F61B}", zh: "吐舌", en: "Face with tongue" },
  { e: "\u{1F61C}", zh: "眨眼吐舌", en: "Winking face with tongue" },
  { e: "\u{1F92A}", zh: "搞怪", en: "Zany face" },
  { e: "\u{1F61D}", zh: "眯眼吐舌", en: "Squinting face with tongue" },
  { e: "\u{1F911}", zh: "财迷脸", en: "Money-mouth face" },
  { e: "\u{1F917}", zh: "抱抱", en: "Hugging face" },
  { e: "\u{1F92D}", zh: "偷笑", en: "Face with hand over mouth" },
  { e: "\u{1F914}", zh: "思考", en: "Thinking face" },
  { e: "\u{1F928}", zh: "挑眉", en: "Raised eyebrow" },
  { e: "\u{1F910}", zh: "闭嘴", en: "Zipper-mouth face" },
  { e: "\u{1F610}", zh: "无语", en: "Neutral face" },
  { e: "\u{1F611}", zh: "面无表情", en: "Expressionless face" },
  { e: "\u{1F636}", zh: "沉默", en: "Face without mouth" },
  { e: "\u{1F60F}", zh: "得意", en: "Smirk" },
  { e: "\u{1F612}", zh: "不爽", en: "Unamused face" },
  { e: "\u{1F644}", zh: "翻白眼", en: "Rolling eyes" },
  { e: "\u{1F62C}", zh: "龇牙咧嘴", en: "Grimacing face" },
  { e: "\u{1F925}", zh: "说谎", en: "Lying face" },
  { e: "\u{1F60C}", zh: "释然", en: "Relieved face" },
  { e: "\u{1F614}", zh: "沉思", en: "Pensive face" },
  { e: "\u{1F625}", zh: "失落", en: "Sad but relieved" },
  { e: "\u{1F622}", zh: "流泪", en: "Crying face" },
  { e: "\u{1F62D}", zh: "大哭", en: "Loudly crying" },
  { e: "\u{1F62A}", zh: "困了", en: "Sleepy face" },
  { e: "\u{1F924}", zh: "流口水", en: "Drooling face" },
  { e: "\u{1F634}", zh: "睡觉", en: "Sleeping face" },
  { e: "\u{1F637}", zh: "口罩", en: "Medical mask" },
  { e: "\u{1F912}", zh: "生病", en: "Face with thermometer" },
  { e: "\u{1F915}", zh: "受伤", en: "Face with head-bandage" },
  { e: "\u{1F922}", zh: "恶心", en: "Nauseated face" },
  { e: "\u{1F92E}", zh: "呕吐", en: "Vomiting face" },
  { e: "\u{1F927}", zh: "打喷嚏", en: "Sneezing face" },
  { e: "\u{1F975}", zh: "好热", en: "Hot face" },
  { e: "\u{1F976}", zh: "好冷", en: "Cold face" },
  { e: "\u{1F974}", zh: "迷糊", en: "Woozy face" },
  { e: "\u{1F635}", zh: "晕", en: "Dizzy face" },
  { e: "\u{1F92F}", zh: "炸了", en: "Exploding head" },
  { e: "\u{1F920}", zh: "牛仔", en: "Cowboy hat face" },
  { e: "\u{1F973}", zh: "庆祝", en: "Partying face" },
  { e: "\u{1F60E}", zh: "墨镜酷", en: "Sunglasses face" },
  { e: "\u{1F913}", zh: "书呆子", en: "Nerd face" },
  { e: "\u{1F9D0}", zh: "单片镜", en: "Monocle face" },
  { e: "\u{1F615}", zh: "困惑", en: "Confused face" },
  { e: "\u{1F61F}", zh: "担心", en: "Worried face" },
  { e: "\u{1F641}", zh: "微皱眉", en: "Slightly frowning" },
  { e: "\u{2639}\u{FE0F}", zh: "皱眉", en: "Frowning face" },
  { e: "\u{1F62E}", zh: "吃惊", en: "Open mouth" },
  { e: "\u{1F62F}", zh: "惊愕", en: "Hushed face" },
  { e: "\u{1F632}", zh: "震惊", en: "Astonished face" },
  { e: "\u{1F633}", zh: "脸红", en: "Flushed face" },
  { e: "\u{1F97A}", zh: "可怜", en: "Pleading face" },
  { e: "\u{1F626}", zh: "皱眉吃惊", en: "Frowning open mouth" },
  { e: "\u{1F627}", zh: "痛苦", en: "Anguished face" },
  { e: "\u{1F628}", zh: "害怕", en: "Fearful face" },
  { e: "\u{1F630}", zh: "焦虑", en: "Anxious face with sweat" },
  { e: "\u{1F631}", zh: "尖叫", en: "Screaming in fear" },
  { e: "\u{1F616}", zh: "难受", en: "Confounded face" },
  { e: "\u{1F623}", zh: "坚持", en: "Persevering face" },
  { e: "\u{1F61E}", zh: "失望", en: "Disappointed face" },
  { e: "\u{1F613}", zh: "汗颜", en: "Downcast with sweat" },
  { e: "\u{1F629}", zh: "崩溃", en: "Weary face" },
  { e: "\u{1F62B}", zh: "疲惫", en: "Tired face" },
  { e: "\u{1F971}", zh: "哈欠", en: "Yawning face" },
  { e: "\u{1F624}", zh: "出气", en: "Steam from nose" },
  { e: "\u{1F621}", zh: "生气", en: "Pouting face" },
  { e: "\u{1F620}", zh: "愤怒", en: "Angry face" },
  { e: "\u{1F92C}", zh: "骂人", en: "Face with symbols on mouth" },
  { e: "\u{1F31A}", zh: "黑脸月亮", en: "New moon face" },
  { e: "\u{1F31D}", zh: "微笑月亮", en: "Full moon face" },
  { e: "\u{1F480}", zh: "骷髅", en: "Skull" },
  { e: "\u{1F921}", zh: "小丑", en: "Clown face" },
  { e: "\u{1F47B}", zh: "鬼魂", en: "Ghost" },
  { e: "\u{1F92B}", zh: "嘘", en: "Shushing face" },
  { e: "\u{1F926}", zh: "扶额", en: "Facepalm" },
  { e: "\u{1F608}", zh: "坏恶魔", en: "Smiling horns" },
  { e: "\u{1F47F}", zh: "怒恶魔", en: "Angry horns" },
  { e: "\u{1F916}", zh: "机器人", en: "Robot" },
  { e: "\u{1F4A9}", zh: "便便", en: "Pile of poo" },
  { e: "\u{1F436}", zh: "狗脸", en: "Dog face" },
  { e: "\u{1F431}", zh: "猫脸", en: "Cat face" },
  { e: "\u{1F389}", zh: "拉炮彩带", en: "Party popper" },
  { e: "\u{1F3C6}", zh: "奖杯", en: "Trophy" },
  { e: "\u{1F42E}", zh: "奶牛头", en: "Cow face" },
  { e: "\u{1F648}", zh: "非礼勿视", en: "See-no-evil" },
  { e: "\u{1F44D}", zh: "赞", en: "Thumbs up" },
  { e: "\u{1F44E}", zh: "踩", en: "Thumbs down" },
  { e: "\u{1F44C}", zh: "OK 手势", en: "OK hand" },
  { e: "\u{270C}\u{FE0F}", zh: "剪刀手", en: "Victory hand" },
  { e: "\u{1F91E}", zh: "交叉手指", en: "Crossed fingers" },
  { e: "\u{1F91F}", zh: "爱你手势", en: "Love-you gesture" },
  { e: "\u{1F918}", zh: "摇滚", en: "Sign of the horns" },
  { e: "\u{1F919}", zh: "打电话", en: "Call me hand" },
  { e: "\u{1F448}", zh: "指左", en: "Backhand left" },
  { e: "\u{1F449}", zh: "指右", en: "Backhand right" },
  { e: "\u{1F446}", zh: "指上", en: "Up-pointing" },
  { e: "\u{1F447}", zh: "指下", en: "Down-pointing" },
  { e: "\u{261D}\u{FE0F}", zh: "指上面", en: "Index up" },
  { e: "\u{1F44B}", zh: "挥手", en: "Waving hand" },
  { e: "\u{1F91A}", zh: "手背", en: "Raised back of hand" },
  { e: "\u{270B}", zh: "举手", en: "Raised hand" },
  { e: "\u{1F44F}", zh: "鼓掌", en: "Clapping" },
  { e: "\u{1F64C}", zh: "双手举高", en: "Raising hands" },
  { e: "\u{1F91D}", zh: "握手", en: "Handshake" },
  { e: "\u{1F64F}", zh: "拜托", en: "Folded hands" },
  { e: "\u{1F647}", zh: "谢谢", en: "Person bowing" },
  { e: "\u{1F4AA}", zh: "加油", en: "Flexed biceps" },
  { e: "\u{1F440}", zh: "看", en: "Eyes" },
  { e: "\u{270D}\u{FE0F}", zh: "写字", en: "Writing hand" },
  { e: "\u{270A}", zh: "拳头", en: "Raised fist" },
  { e: "\u{1F590}\u{FE0F}", zh: "张开手", en: "Splayed hand" },
  { e: "\u{1F91B}", zh: "左拳", en: "Left fist" },
  { e: "\u{1F91C}", zh: "右拳", en: "Right fist" },
  { e: "\u{1F90F}", zh: "捏一把", en: "Pinching hand" },
  { e: "\u{2764}\u{FE0F}", zh: "红心", en: "Red heart" },
  { e: "\u{1F494}", zh: "心碎", en: "Broken heart" },
  { e: "\u{2763}\u{FE0F}", zh: "心形感叹", en: "Heart exclamation" },
  { e: "\u{1F495}", zh: "两颗心", en: "Two hearts" },
  { e: "\u{1F49E}", zh: "旋转的心", en: "Revolving hearts" },
  { e: "\u{1F493}", zh: "心跳", en: "Beating heart" },
  { e: "\u{1F496}", zh: "闪亮的心", en: "Sparkling heart" },
  { e: "\u{1F498}", zh: "一箭穿心", en: "Heart with arrow" },
  { e: "\u{1F49D}", zh: "心意礼物", en: "Heart with ribbon" },
  { e: "\u{1F339}", zh: "玫瑰", en: "Rose" },
  { e: "\u{1F940}", zh: "凋谢", en: "Wilted flower" },
  { e: "\u{1F349}", zh: "西瓜", en: "Watermelon" },
  { e: "\u{1F38A}", zh: "彩球", en: "Confetti ball" },
  { e: "\u{1F381}", zh: "礼物", en: "Gift" },
  { e: "\u{1F4AF}", zh: "满分", en: "Hundred points" },
  { e: "\u{1F680}", zh: "火箭", en: "Rocket" },
  { e: "\u{1F4A1}", zh: "点子", en: "Light bulb" },
  { e: "\u{2705}", zh: "完成", en: "Check mark" },
  { e: "\u{274C}", zh: "叉号", en: "Cross mark" },
  { e: "\u{26A1}", zh: "闪电", en: "Lightning" },
  { e: "\u{1F525}", zh: "火", en: "Fire" },
  { e: "\u{1F308}", zh: "彩虹", en: "Rainbow" },
  { e: "\u{2B50}", zh: "星星", en: "Star" },
  { e: "\u{1F31F}", zh: "闪亮星", en: "Glowing star" },
  { e: "\u{2728}", zh: "闪光", en: "Sparkles" },
  { e: "\u{1F4A5}", zh: "碰撞", en: "Collision" },
  { e: "\u{1F4AB}", zh: "眩晕", en: "Dizzy" },
  { e: "\u{1F4A2}", zh: "怒气", en: "Anger symbol" },
  { e: "\u{1F300}", zh: "晕", en: "Cyclone" },
  { e: "\u{1F192}", zh: "给力", en: "Cool button" },
  { e: "\u{1F4A3}", zh: "炸弹", en: "Bomb" },
  { e: "\u{1F528}", zh: "敲打", en: "Hammer" },
  { e: "\u{1F382}", zh: "生日蛋糕", en: "Birthday cake" },
  { e: "\u{1F942}", zh: "碰杯", en: "Clinking glasses" },
];

const CUSTOM_EMOJIS: EmojiItem[] = CUSTOM_EMOJI_URLS.map((url, index) => ({
  e: `[emoji:${url}]`,
  zh: `自定义表情 ${index + 1}`,
  en: `Custom emoji ${index + 1}`,
  src: url,
}));

const EMOJI_BY_E = new Map(
  [...EMOJIS, ...CUSTOM_EMOJIS].map((item) => [item.e, item]),
);

const RECENT_STORAGE_KEY = "community.emoji.recent";
const RECENT_MAX = 14;

interface CommentEmojiPickerProps {
  /** Returns the native textarea so picks insert at the cursor. */
  getEditor: () => HTMLTextAreaElement | null;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/** Comment composer emoji entry: picks insert at the cursor position. */
export default function CommentEmojiPicker({
  getEditor,
  onChange,
  disabled = false,
}: CommentEmojiPickerProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const isZh = (i18n.resolvedLanguage || i18n.language || "").startsWith("zh");
  const [recent, setRecent] = useState<string[]>(() => {
    try {
      const raw = window.localStorage.getItem(RECENT_STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed)
        ? parsed
            .filter((x): x is string => typeof x === "string")
            .slice(0, RECENT_MAX)
        : [];
    } catch {
      return [];
    }
  });
  const [tab, setTab] = useState<"default" | "custom">("default");

  // Mount tooltips after the open animation so 200+ popovers don't lag.
  const [tooltipsReady, setTooltipsReady] = useState(false);
  useEffect(() => {
    if (!open || tooltipsReady) return;
    const timer = window.setTimeout(() => setTooltipsReady(true), 200);
    return () => window.clearTimeout(timer);
  }, [open, tooltipsReady]);

  const getEditorRef = useRef(getEditor);
  getEditorRef.current = getEditor;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const handlePick = useCallback((item: EmojiItem) => {
    const editor = getEditorRef.current();
    const base = editor?.value ?? "";
    const start = editor?.selectionStart ?? base.length;
    const end = editor?.selectionEnd ?? base.length;
    onChangeRef.current(base.slice(0, start) + item.e + base.slice(end));
    const pos = start + item.e.length;
    window.requestAnimationFrame(() => {
      editor?.focus();
      editor?.setSelectionRange(pos, pos);
    });
    if (!item.src) {
      setRecent((prev) => {
        const next = [item.e, ...prev.filter((x) => x !== item.e)].slice(
          0,
          RECENT_MAX,
        );
        try {
          window.localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // Storage may be unavailable; recent row is best-effort.
        }
        return next;
      });
    }
    setOpen(false);
  }, []);

  const renderEmojiButton = useCallback(
    (item: EmojiItem) => {
      const button = (
        <button
          type="button"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => handlePick(item)}
          className={item.src ? styles.emojiCustomCell : styles.emojiCell}
        >
          {item.src ? (
            <img
              src={item.src}
              alt={isZh ? item.zh : item.en}
              loading="lazy"
              // Inline metrics keep the sticker flush with its 66x66 cell
              // even if a stale CSS generation drops the module rules.
              style={{
                width: 66,
                height: 66,
                objectFit: "fill",
                display: "block",
              }}
            />
          ) : (
            item.e
          )}
        </button>
      );
      if (!tooltipsReady || item.src) {
        return <Fragment key={item.e}>{button}</Fragment>;
      }
      return (
        <Tooltip key={item.e} title={isZh ? item.zh : item.en}>
          {button}
        </Tooltip>
      );
    },
    [tooltipsReady, isZh, handlePick],
  );

  const defaultContent = useMemo(() => {
    const recentItems = recent
      .map((e) => EMOJI_BY_E.get(e))
      .filter((item): item is EmojiItem => !!item && !item.src);
    return (
      <>
        {recentItems.length > 0 ? (
          <div>
            <p className={styles.emojiSectionTitle}>
              {t("communityPage.emojiRecent")}
            </p>
            <div className={styles.emojiGrid}>
              {recentItems.map(renderEmojiButton)}
            </div>
            <div className={styles.emojiDivider} />
          </div>
        ) : null}
        <p className={styles.emojiSectionTitle}>
          {t("communityPage.emojiAll")}
        </p>
        <div className={styles.emojiGrid}>{EMOJIS.map(renderEmojiButton)}</div>
      </>
    );
  }, [recent, t, renderEmojiButton]);

  const customContent = useMemo(
    () => (
      <>
        <p className={styles.emojiSectionTitle}>
          {t("communityPage.emojiCustom")}
        </p>
        <div className={`${styles.emojiGrid} ${styles.emojiCustomGrid}`}>
          {CUSTOM_EMOJIS.map(renderEmojiButton)}
        </div>
      </>
    ),
    [t, renderEmojiButton],
  );

  return (
    <Popover
      open={open}
      overlayClassName={styles.emojiPopover}
      onOpenChange={(next) => {
        if (!disabled) setOpen(next);
      }}
      trigger="click"
      placement="bottomLeft"
      content={
        <div className={styles.emojiPanel}>
          <div hidden={tab !== "default"} className={styles.emojiScroll}>
            {defaultContent}
          </div>
          <div hidden={tab !== "custom"} className={styles.emojiScroll}>
            {customContent}
          </div>
          <div className={styles.emojiTabBar}>
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => setTab("default")}
              title={t("communityPage.emojiAll")}
              aria-label={t("communityPage.emojiAll")}
              className={`${styles.emojiTab} ${
                tab === "default" ? styles.emojiTabActive : ""
              }`}
            >
              {"😀"}
            </button>
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => setTab("custom")}
              title={t("communityPage.emojiCustom")}
              aria-label={t("communityPage.emojiCustom")}
              className={`${styles.emojiTab} ${
                tab === "custom" ? styles.emojiTabActive : ""
              }`}
            >
              <img src={CUSTOM_EMOJI_URLS[2]} alt="" loading="lazy" />
            </button>
          </div>
        </div>
      }
    >
      <button
        type="button"
        title={t("communityPage.addEmoji")}
        aria-label={t("communityPage.addEmoji")}
        disabled={disabled}
        onMouseDown={(event) => event.preventDefault()}
        className={`${styles.emojiTrigger} ${
          open ? styles.emojiTriggerOpen : ""
        }`}
      >
        <Smile size={16} aria-hidden="true" />
      </button>
    </Popover>
  );
}
