import { File, Paths } from "expo-file-system";
import * as MediaLibrary from "expo-media-library/legacy";
import * as Sharing from "expo-sharing";

import { mediaSource } from "../../api/client";
import type { Connection, DisplayPart } from "../../api/types";

export async function saveImageToLibrary(
  connection: Connection,
  part: Exclude<DisplayPart, { type: "text" }>,
): Promise<void> {
  const permission = await MediaLibrary.requestPermissionsAsync(true);
  if (!permission.granted) throw new Error("没有照片写入权限。");
  const file = await cacheMedia(connection, part);
  await MediaLibrary.saveToLibraryAsync(file.uri);
}

export async function shareMedia(
  connection: Connection,
  part: Exclude<DisplayPart, { type: "text" }>,
): Promise<void> {
  if (!await Sharing.isAvailableAsync()) {
    throw new Error("当前设备不支持系统分享。");
  }
  const file = await cacheMedia(connection, part);
  await Sharing.shareAsync(file.uri);
}

async function cacheMedia(
  connection: Connection,
  part: Exclude<DisplayPart, { type: "text" }>,
): Promise<File> {
  const source = mediaSource(connection, part.url);
  const response = await fetch(source.uri, { headers: source.headers });
  if (!response.ok) throw new Error(`文件下载失败（${response.status}）`);
  const name = safeName(part.name || fileName(part.url) || defaultName(part.type));
  const file = new File(Paths.cache, `${Date.now()}-${name}`);
  file.create({ overwrite: true });
  file.write(new Uint8Array(await response.arrayBuffer()));
  return file;
}

function safeName(value: string): string {
  return value.replace(/[^\w.\-一-鿿]/g, "-").slice(-100) || "qwenpaw-file";
}

function fileName(value: string): string {
  return value.replace(/\\/g, "/").split("/").pop()?.split("?")[0] ?? "";
}

function defaultName(type: Exclude<DisplayPart, { type: "text" }>['type']): string {
  if (type === "image") return "qwenpaw-image.png";
  if (type === "video") return "qwenpaw-video.mp4";
  if (type === "audio") return "qwenpaw-audio.m4a";
  return "qwenpaw-file";
}
