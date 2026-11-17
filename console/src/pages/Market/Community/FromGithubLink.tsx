import { useTranslation } from "react-i18next";
import { SparkGithubGithubFill } from "@agentscope-ai/icons";
import { openExternalLink } from "@/utils/openExternalLink";
import { isGithubRepoLink, normalizeGithubLink } from "./githubLink";
import styles from "./index.module.less";

const ExternalLinkIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
    <path
      d="M3 9L9 3M9 3H4M9 3V8"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/**
 * Detail-page "From GitHub" orange external link, mirroring the Platform
 * FromGithubLink component; shown beside the author row when the post
 * carries a github_link.
 */
export function FromGithubLink({ href }: { href: string }) {
  const { t } = useTranslation();
  // Server pass-through value: only render links that parse as a GitHub
  // repository URL and canonicalize the href, because middle-click/auxclick
  // bypass the onClick guard below and follow the raw href.
  if (!isGithubRepoLink(href)) return null;
  const url = normalizeGithubLink(href);
  return (
    <a
      href={url}
      className={styles.fromGithubLink}
      onClick={(event) => {
        event.preventDefault();
        openExternalLink(url);
      }}
    >
      <SparkGithubGithubFill size={16} className={styles.fromGithubIcon} />
      {t("communityPage.fromGithub")}
      <ExternalLinkIcon />
    </a>
  );
}
