import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";
import {
  isSupportedExternalHref,
  openExternalLink,
} from "../utils/openExternalLink";

interface MarkdownExternalLinkProps
  extends AnchorHTMLAttributes<HTMLAnchorElement> {
  children?: ReactNode;
  node?: unknown;
}

export function MarkdownExternalLink({
  href,
  children,
  onClick,
  node: _node,
  ...props
}: MarkdownExternalLinkProps) {
  const externalHref = isSupportedExternalHref(href) ? href : undefined;

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || !externalHref) {
      return;
    }
    event.preventDefault();
    openExternalLink(externalHref);
  };

  return (
    <a
      {...props}
      href={href}
      target={externalHref ? props.target ?? "_blank" : props.target}
      rel={externalHref ? props.rel ?? "noopener noreferrer" : props.rel}
      onClick={handleClick}
    >
      {children}
    </a>
  );
}
