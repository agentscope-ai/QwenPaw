export type ReleaseNoteMeta = { version: string; date?: string };

export const RELEASE_NOTES_DATA: ReleaseNoteMeta[] = [
  { version: "v1.1.12" },
  { version: "v1.1.11" },
  { version: "v1.1.10" },
  { version: "v1.1.9" },
  { version: "v1.1.8" },
  { version: "v1.1.7" },
  { version: "v1.1.6" },
  { version: "v1.1.5" },
  { version: "v1.1.4" },
  { version: "v1.1.3" },
  { version: "v1.1.2" },
  { version: "v1.1.1" },
  { version: "v1.1.0" },
  { version: "v1.0.2" },
  { version: "v1.0.1" },
  { version: "v1.0.0" },
  { version: "v0.2.0" },
  { version: "v0.1.0" },
  { version: "v0.0.7" },
  { version: "v0.0.6" },
  { version: "v0.0.5" },
  { version: "v0.0.4" },
];

export const LATEST_RELEASE_VERSION = RELEASE_NOTES_DATA[0]!.version;
