/** CDN URLs for channel logos — shared by Channel settings cards and Chat session list. */
export const CHANNEL_ICON_URLS: Record<string, string> = {
  dingtalk:
    "https://gw.alicdn.com/imgextra/i4/O1CN01g1u9vB1KdEreWzDdv_!!6000000001186-2-tps-400-400.png",
  voice:
    "https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png",
  qq: "https://gw.alicdn.com/imgextra/i3/O1CN014wGNgd27PsTzAyrcj_!!6000000007790-2-tps-400-400.png",
  feishu:
    "https://gw.alicdn.com/imgextra/i4/O1CN01jsn08m225euyUoaFN_!!6000000007069-2-tps-400-400.png",
  xiaoyi:
    "https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png",
  telegram:
    "https://gw.alicdn.com/imgextra/i2/O1CN0100jIva25Dqqq1VqJN_!!6000000007493-2-tps-400-400.png",
  mqtt: "https://gw.alicdn.com/imgextra/i2/O1CN0117Adu3282o9G5ZNCd_!!6000000007875-2-tps-400-400.png",
  imessage:
    "https://gw.alicdn.com/imgextra/i1/O1CN016pwG4m1uEntwJKsGl_!!6000000006006-2-tps-400-400.png",
  discord:
    "https://gw.alicdn.com/imgextra/i4/O1CN01BQFnBu21PWTtKbPmU_!!6000000006977-2-tps-400-400.png",
  mattermost:
    "https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png",
  matrix:
    "https://gw.alicdn.com/imgextra/i3/O1CN01CQSF5R29JaGuuzZ5X_!!6000000008047-2-tps-320-320.png",
  console:
    "https://gw.alicdn.com/imgextra/i4/O1CN01eeLWyo1ZgBePACyWf_!!6000000003223-2-tps-320-320.png",
  wecom:
    "https://gw.alicdn.com/imgextra/i1/O1CN01HWtzmr1hkK9beQICJ_!!6000000004315-2-tps-400-400.png",
  weixin:
    "https://gw.alicdn.com/imgextra/i4/O1CN01GsAob11fkfDWVIb3R_!!6000000004045-2-tps-400-400.png",
};

export const CHANNEL_DEFAULT_ICON_URL =
  "https://gw.alicdn.com/imgextra/i3/O1CN01CQSF5R29JaGuuzZ5X_!!6000000008047-2-tps-320-320.png";

export function getChannelIconUrl(channelKey: string): string {
  return CHANNEL_ICON_URLS[channelKey] ?? CHANNEL_DEFAULT_ICON_URL;
}
