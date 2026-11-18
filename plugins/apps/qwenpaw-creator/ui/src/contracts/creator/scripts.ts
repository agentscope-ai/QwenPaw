/** 剧本直登结果：正文由服务端落版本，前端拿到的只是版本身份。 */
export interface TimelineScriptImportResult {
  resultKind: "script_import";
  projectId: string;
  timelineId: string;
  slotId: string;
  artifactVersionId: string;
  fileId: string;
  checksum: string;
  blockCount: number;
  characterCount: number;
  generation: number;
  etag: string;
  /** 与当前已选剧本内容一致时为 true：不产生新版本，也不推进 generation。 */
  replayed: boolean;
  /** 项目要求审阅时非空：剧本进入待审，通过后才会成为当前版本。 */
  reviewId: string | null;
  changedPointers: string[];
  summary: string;
}
