// Platform comment emoji assets; keep in sync with platform-front customEmoji.tsx.
export const CUSTOM_EMOJI_URLS = [
  "https://img.alicdn.com/imgextra/i4/O1CN01Yz8ONFQWTVL0IsjU_!!6000000000993-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01eby7UGC9qeJ0IsjU_!!6000000002569-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN01k14kON7Q30H0IsjU_!!6000000003688-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01Xeab3t9TplG0IsjU_!!6000000000546-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01aTrUvUP23EJ0IsjU_!!6000000006659-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN011v8Yn2xzoeC0IsjU_!!6000000001695-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01SiFEJJst4FJ0IsjU_!!6000000007315-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01JMKuCC5qbsC0IsjU_!!6000000001734-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01qfVMcdNnvnG0IsjU_!!6000000002847-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN0127vq41zhvPC0IsjU_!!6000000002945-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN01BB6wvQU8UHH0IsjU_!!6000000006101-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01I8uPPX1F6bL0IsjU_!!6000000005991-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN01efxiNuILaXH0IsjU_!!6000000002866-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01wO2isACJu0D0IsjU_!!6000000004653-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01qxWrNQw3TWK0IsjU_!!6000000004808-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01HUKKGcdo3nK0IsjU_!!6000000007026-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i4/O1CN010WZ20lbdDbC0IsjU_!!6000000006353-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01KfZDqHUjj9F0IsjU_!!6000000007462-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01ycrU7KR66vI0IsjU_!!6000000000313-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN01J3NDKVeIqcI0IsjU_!!6000000005806-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i1/O1CN014Dl4hLIMCFK0IsjU_!!6000000003024-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i2/O1CN01sq1jwcJdiMK0IsjU_!!6000000007630-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i4/O1CN01d6TatGsJYzI0IsjU_!!6000000002931-2-tps-150-150.png",
  "https://img.alicdn.com/imgextra/i3/O1CN01b9hFkFp46rF0IsjU_!!6000000002946-2-tps-150-150.png",
];
const allowed = new Set(CUSTOM_EMOJI_URLS);
export function isCustomEmoji(src: string | undefined): boolean {
  return typeof src === "string" && allowed.has(src);
}
export function markdownWithCustomEmoji(content: string): string {
  return content.replace(/\[emoji:([^\]\n]+)\]/g, (token, url: string) =>
    allowed.has(url) ? `![emoji](<${url}>)` : token,
  );
}
