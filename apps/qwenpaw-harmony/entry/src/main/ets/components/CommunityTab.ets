/*
 * 社区 tab —— 一期占位（节点社区：节点发现 / 共享工作区，二期接入）。
 */

@Component
export struct CommunityTab {
  build() {
    Column() {
      Text($r('app.string.community_title'))
        .fontSize(28)
        .fontWeight(FontWeight.Bold)
        .fontColor($r('app.color.text_primary_strong'))
      Text($r('app.string.community_desc'))
        .fontSize(14)
        .fontColor($r('app.color.text_secondary'))
        .margin({ top: 12 })
        .textAlign(TextAlign.Center)
        .lineHeight(22)
        .padding({ left: 32, right: 32 })
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .backgroundColor($r('app.color.page_bg'))
  }
}
