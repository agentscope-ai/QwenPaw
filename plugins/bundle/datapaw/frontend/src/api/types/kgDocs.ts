export interface KgDocsApiEnvelope<T> {
  code: number;
  message: string;
  data: T | null;
}

export interface KgDocument {
  doc_id: string;
  filename: string;
  file_size: number;
  download_url: string;
}

export interface KgDocsListData {
  list: KgDocument[];
  page: number;
  page_size: number;
  total: number;
}

export interface KgDocsDeleteData {
  doc_id: string;
}
