import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { openExternalLink } from "@/utils/openExternalLink";
import type { Post } from "./api";
import { assignHeadingIds, sanitizeArticleHtml } from "./articleToc";
import { ImageLightbox } from "./ImageLightbox";
import { mediaUrl, videoUrl } from "./media";
import styles from "./index.module.less";

export function Video({ src, label }: { src: string; label?: string }) {
  const { t } = useTranslation();
  return (
    <span className={styles.videoBlock}>
      <video
        src={src}
        controls
        playsInline
        preload="metadata"
        aria-label={label || t("communityPage.video")}
      />
    </span>
  );
}

/** Markdown renderers that play video URLs inline; shared by every draft
 *  preview so uploaded videos render as players instead of broken images. */
export const videoMarkdownComponents = {
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    const src = videoUrl(href);
    return src ? (
      <Video src={src} />
    ) : (
      <CommunityAnchor href={href}>{children}</CommunityAnchor>
    );
  },
  img: ({ src, alt }: { src?: string; alt?: string }) => {
    const url = videoUrl(src);
    return url ? (
      <Video src={url} label={alt} />
    ) : (
      <img src={mediaUrl(src)} alt={alt || ""} loading="lazy" />
    );
  },
};

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
  const [preview, setPreview] = useState<{ src: string; alt: string } | null>(
    null,
  );
  const handleBodyClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    // Body images open the fullscreen lightbox instead of navigating.
    if (target instanceof HTMLImageElement) {
      const src = target.currentSrc || target.src;
      if (!src) return;
      event.preventDefault();
      event.stopPropagation();
      setPreview({ src, alt: target.alt || "" });
      return;
    }
    const link = target.closest("a");
    const href = link?.getAttribute("href");
    if (!href || href.startsWith("#")) return;
    event.preventDefault();
    const url = mediaUrl(href);
    if (url) openExternalLink(url);
  };
  const html = useMemo(() => {
    const root = document.createElement("div");
    root.innerHTML = sanitizeArticleHtml(post.body_html || "");
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
    });
    // Wide tables scroll horizontally inside a wrapper like the platform body.
    root.querySelectorAll("table").forEach((table) => {
      if (table.closest(`.${styles.tableWrap}`)) return;
      const wrap = document.createElement("div");
      wrap.className = styles.tableWrap;
      table.replaceWith(wrap);
      wrap.appendChild(table);
    });
    assignHeadingIds(root);
    return root.innerHTML;
  }, [post.body_html, t]);
  return (
    <>
      {html ? (
        <div
          className={styles.body}
          dangerouslySetInnerHTML={{ __html: html }}
          onClick={handleBodyClick}
        />
      ) : (
        <MarkdownFallback post={post} onBodyClick={handleBodyClick} />
      )}
      <ImageLightbox
        src={preview?.src ?? null}
        alt={preview?.alt ?? ""}
        onClose={() => setPreview(null)}
      />
    </>
  );
}

/** Markdown fallback; heading ids follow render order like parseMarkdownToc. */
function MarkdownFallback({
  post,
  onBodyClick,
}: {
  post: Post;
  onBodyClick: React.MouseEventHandler<HTMLDivElement>;
}) {
  const counter = { index: 0 };
  const heading = (level: number) => {
    const Tag = `h${level}` as React.ElementType;
    return function MarkdownHeading({
      children,
    }: {
      children?: React.ReactNode;
    }) {
      return <Tag id={`md-heading-${counter.index++}`}>{children}</Tag>;
    };
  };
  return (
    <div className={styles.body} onClick={onBodyClick}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          ...videoMarkdownComponents,
          table: ({ children }) => (
            <div className={styles.tableWrap}>
              <table>{children}</table>
            </div>
          ),
          h1: heading(1),
          h2: heading(2),
          h3: heading(3),
          h4: heading(4),
          h5: heading(5),
          h6: heading(6),
        }}
      >
        {post.body_text || post.summary || ""}
      </ReactMarkdown>
    </div>
  );
}
