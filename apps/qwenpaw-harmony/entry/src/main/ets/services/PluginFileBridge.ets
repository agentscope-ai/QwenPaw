/*
 * 插件文件读取桥（javaScriptProxy）—— ArkWeb 对 file:// 的 fetch 被 CORS 拦截
 * （官方 scheme 白名单不含 file），ESM 形态的插件 bundle 无法走 fetch→Blob→import 主路径；
 * 由端侧直接从沙箱读文件、base64 回传 Web 侧（host.js 解码后与 console http 路径同管线 import）。
 * 路径白名单：只放行 pluginhost 下 plugins/<id>/… 的读，拒绝越界与路径穿越。
 */
import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';

// 单次读取上限（防异常路径占用内存）
const MAX_READ_SIZE: number = 16 * 1024 * 1024;
// plugins/<id>/<相对路径>：id 遵循插件 id 规则，路径只放行安全字符
const REL_PATTERN: RegExp = /^plugins\/[a-z0-9][a-z0-9_-]*\/[A-Za-z0-9._\-/]+$/;

export class PluginFileBridge {
  private hostDir: string;

  constructor(hostDir: string) {
    this.hostDir = hostDir;
  }

  // Web 侧调用：window.qpwFile.readPluginFile('plugins/<id>/…') → 文件内容 base64；失败返回空串
  readPluginFile(rel: string): string {
    if (typeof rel !== 'string' || !REL_PATTERN.test(rel)) {
      return '';
    }
    const full: string = `${this.hostDir}/${rel}`;
    let f: fileIo.File | null = null;
    try {
      f = fileIo.openSync(full, fileIo.OpenMode.READ_ONLY);
      const size: number = fileIo.statSync(f.fd).size;
      if (size <= 0 || size > MAX_READ_SIZE) {
        return '';
      }
      const buf: ArrayBuffer = new ArrayBuffer(size);
      const len: number = fileIo.readSync(f.fd, buf);
      return new util.Base64Helper().encodeToStringSync(new Uint8Array(buf, 0, len));
    } catch (e) {
      return '';
    } finally {
      if (f !== null) {
        try {
          fileIo.closeSync(f.fd);
        } catch (e) {
          // 忽略关闭失败
        }
      }
    }
  }
}
