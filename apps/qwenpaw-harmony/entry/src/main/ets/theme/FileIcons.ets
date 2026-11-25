/*
 * 文件扩展名 → 图标（聊天文件卡 / 文件页 / 文件树共用一套，避免各页各写一遍）。
 *
 * 分档逐条对齐 console 的 FileGlyph（console/src/features/files-workspace/FileGlyph.tsx）：
 *   文本（md/mdx/txt/log/csv）→ FileText；代码（py/ts/tsx/js/jsx/go/rs/java/html/css）→ FileCode2；
 *   其余 → File（通用文件）。图标全部是本工程的 lucide 填充几何（tools/stroke_to_fill.py 生成），
 *   不用 emoji——emoji 在不同字体/深浅色下字形与着色都不可控。
 */

const TEXT_EXTS: string[] = ['md', 'mdx', 'txt', 'log', 'csv'];
const CODE_EXTS: string[] = ['py', 'ts', 'tsx', 'js', 'jsx', 'go', 'rs', 'java', 'html', 'css'];

export function fileIconOf(name: string): Resource {
  const dot: number = name.lastIndexOf('.');
  const ext: string = dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
  if (TEXT_EXTS.indexOf(ext) >= 0) {
    return $r('app.media.file_text');
  }
  if (CODE_EXTS.indexOf(ext) >= 0) {
    return $r('app.media.file_code');
  }
  return $r('app.media.file');
}
