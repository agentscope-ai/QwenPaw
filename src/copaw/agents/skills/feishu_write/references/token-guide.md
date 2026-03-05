# Token 获取指南

本文档说明飞书文档写入工具中涉及的各类 token 的用途和获取方法。

## Token 类型总览

| Token 名称 | 用途 | 格式特征 | 使用场景 |
|-----------|------|---------|---------|
| `folder_token` | 指定云空间文件夹 | 字母数字混合字符串 | `--target folder` |
| `node_token` | 指定知识库节点 | 字母数字混合字符串 | `--target wiki` |
| `space_id` | 知识库内部标识 | 纯数字 | 自动查询，一般无需手动获取 |

## 1. 文件夹 Folder Token

### 用途

写入到云空间指定文件夹时需要此 token。可通过 `--folder-token` 参数传入，或配置在 `.env` 的 `FEISHU_DEFAULT_FOLDER_TOKEN` 中作为默认值。

### 获取方式

1. 在飞书中打开目标文件夹
2. 查看浏览器地址栏，URL 格式为：
   ```
   https://xxx.feishu.cn/drive/folder/LlqxfXXXXXXXXXX
   ```
3. URL 中 `/folder/` 后面的字符串即为 `folder_token`

### 格式特征

- 字母数字混合字符串
- 示例：`LlqxfXt5jlyqdnd3VYzcASuOnEc`

### 配置为默认值

如果你经常写入同一个文件夹，可以将 token 配置在 `.env` 中：

```dotenv
FEISHU_DEFAULT_FOLDER_TOKEN=LlqxfXt5jlyqdnd3VYzcASuOnEc
```

配置后，使用 `--target folder` 时无需再传 `--folder-token` 参数。

## 2. 知识库 Node Token

### 用途

写入到知识库指定节点下时需要此 token。可通过 `--wiki-token` 参数传入，或配置在 `.env` 的 `FEISHU_DEFAULT_WIKI_NODE_TOKEN` 中作为默认值。

### 获取方式

1. 在飞书中打开目标知识库页面（可以是知识库首页或任意子节点）
2. 查看浏览器地址栏，URL 格式为：
   ```
   https://xxx.feishu.cn/wiki/FWn9wEcZhixVLrk2z5scBx8DnTe
   ```
3. URL 中 `/wiki/` 后面的字符串即为 `node_token`

### 格式特征

- 字母数字混合的字符串
- 示例：`FWn9wEcZhixVLrk2z5scBx8DnTe`

### 配置为默认值

```dotenv
FEISHU_DEFAULT_WIKI_NODE_TOKEN=FWn9wEcZhixVLrk2z5scBx8DnTe
```

配置后，使用 `--target wiki` 时无需再传 `--wiki-token` 参数。

### 注意事项

- `node_token` 指定的是文档将被创建在哪个节点 **下方**
- 如果传入的是知识库根节点的 token，文档将创建在知识库顶层
- 如果传入的是某个文档节点的 token，新文档将创建为该节点的子文档

## 3. 知识库 Space ID

### 用途

创建知识库文档时的 API 必需参数。**程序会自动通过 node_token 查询 space_id**，一般无需手动获取。

### 获取方式

- **自动获取（推荐）**：只需提供 `node_token`，程序会调用飞书 API 自动查询对应的 `space_id`
- **手动配置（可选）**：如果需要手动配置，可在 `.env` 中设置：

```dotenv
FEISHU_DEFAULT_WIKI_SPACE_ID=7123456789
```

### 格式特征

- 纯数字
- 示例：`7123456789`

## 快速验证 Token 格式

如果你不确定获取的 token 是否正确，可以通过以下特征快速校验：

| 你想做什么 | 需要的 Token | URL 中的位置 | 格式检查 |
|-----------|-------------|-------------|---------|
| 写入到文件夹 | folder_token | `/drive/folder/` 后面 | 字母数字混合字符串 |
| 写入到知识库 | node_token | `/wiki/` 后面 | 字母数字混合字符串 |
