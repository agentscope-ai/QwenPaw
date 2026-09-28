/** Keep server path spelling, including drive and network-share roots. */
export function directoryBreadcrumbs(path: string) {
  const root =
    path.match(
      /^(?:[a-z]:[\\/]|[\\/]{2}[^\\/]+[\\/][^\\/]+[\\/]?|[\\/])/i,
    )?.[0] || "";
  const crumbs = root ? [{ label: root, path: root }] : [];
  for (const match of path.slice(root.length).matchAll(/[^\\/]+/g)) {
    crumbs.push({
      label: match[0],
      path: path.slice(0, root.length + match.index + match[0].length),
    });
  }
  return crumbs;
}
