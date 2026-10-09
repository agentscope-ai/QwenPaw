import { useMemo, useState } from "react";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { openExternalLink } from "@/utils/openExternalLink";
import type { Post } from "./api";
import { mediaUrl, videoUrl } from "./media";
import styles from "./index.module.less";

function Video({ src, label }: { src: string; label?: string }) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  return (
    <span className={styles.videoBlock}>
      <video
        src={src}
        controls
        playsInline
        preload="metadata"
        aria-label={label || t("communityPage.video")}
        onError={() => setFailed(true)}
      />
      <span className={styles.mediaCaption}>
        {failed && <span>{t("communityPage.videoFailed")} </span>}
        <CommunityAnchor href={src}>
          {t("communityPage.openVideo")}
        </CommunityAnchor>
      </span>
    </span>
  );
}
export function CommunityAnchor({
  href,
  children,
}: {
  href?: string;
  children?: React.ReactNode;
}) {
  return (
    <a
      href={href}
      onClick={(event) => {
        if (!href || href.startsWith("#")) return;
        event.preventDefault();
        const url = mediaUrl(href);
        if (url) openExternalLink(url);
      }}
    >
      {children}
    </a>
  );
}

export function PostBody({ post }: { post: Post }) {
  const { t } = useTranslation();
  const html = useMemo(() => {
    const root = document.createElement("div");
    root.innerHTML = DOMPurify.sanitize(post.body_html || "", {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "form", "input", "button", "iframe", "audio"],
      FORBID_ATTR: ["style", "id", "name", "srcset", "autoplay", "loop"],
    });
    // Platform stores uploaded videos both as video tags and image/link nodes.
    root.querySelectorAll("a[href],img[src]").forEach((node) => {
      const src = videoUrl(
        node.getAttribute(node.tagName === "A" ? "href" : "src") || "",
      );
      if (!src) return;
      const video = document.createElement("video");
      video.src = src;
      node.replaceWith(video);
    });
    root.querySelectorAll("video").forEach((video) => {
      const src = mediaUrl(video.getAttribute("src") || undefined);
      if (src) video.src = videoUrl(src) || src;
      else video.removeAttribute("src");
      video.querySelectorAll("source").forEach((source) => {
        const safe = mediaUrl(source.getAttribute("src") || undefined);
        if (safe) source.src = videoUrl(safe) || safe;
        else source.remove();
      });
      const safeSrc =
        video.getAttribute("src") || video.querySelector("source")?.src;
      if (!safeSrc) {
        video.remove();
        return;
      }
      video.controls = true;
      video.playsInline = true;
      video.preload = "metadata";
      video.setAttribute("aria-label", t("communityPage.video"));
      const fallback = document.createElement("a");
      fallback.href = safeSrc;
      fallback.textContent = t("communityPage.openVideo");
      fallback.className = styles.mediaCaption;
      video.after(fallback);
    });
    return root.innerHTML;
  }, [post.body_html, t]);
  return html ? (
    <div
      className={styles.body}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={(event) => {
        const link = (event.target as Element).closest("a");
        const href = link?.getAttribute("href");
        if (!href || href.startsWith("#")) return;
        event.preventDefault();
        const url = mediaUrl(href);
        if (url) openExternalLink(url);
      }}
    />
  ) : (
    <div className={styles.body}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const src = videoUrl(href);
            return src ? (
              <Video src={src} />
            ) : (
              <CommunityAnchor href={href}>{children}</CommunityAnchor>
            );
          },
          img: ({ src, alt }) => {
            const url = videoUrl(src);
            return url ? (
              <Video src={url} label={alt} />
            ) : (
              <img src={mediaUrl(src)} alt={alt || ""} loading="lazy" />
            );
          },
        }}
      >
        {post.body_text || post.summary || ""}
      </ReactMarkdown>
    </div>
  );
}
