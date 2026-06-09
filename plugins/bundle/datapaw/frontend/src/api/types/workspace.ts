export interface MdFileInfo {
  filename: string;
  path: string;
  size: number;
  created_time: string;
  modified_time: string;
}

export interface MdFileContent {
  content: string;
}

export interface MarkdownFile extends MdFileInfo {
  updated_at: number;
  enabled?: boolean;
}

export interface DailyMemoryFile extends MdFileInfo {
  date: string;
  updated_at: number;
}
