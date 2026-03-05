# 飞书应用配置指南

本文档指导你完成飞书应用的创建、权限配置和协作者添加，以便使用飞书文档写入工具。

## 1. 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/app)
2. 点击 **「创建企业自建应用」**
3. 填写应用名称和描述（如"文档写入工具"）
4. 创建成功后，进入应用详情页
5. 在 **「凭证与基础信息」** 页面获取：
   - **App ID**：应用唯一标识
   - **App Secret**：应用密钥（注意保密）

## 2. 开通应用权限

进入应用详情页 > **「权限管理」**，搜索并开通以下权限：

| 权限标识 | 权限名称 | 用途 | 是否必需 |
|---------|---------|------|---------|
| `docx:document` | 云空间文档 | 创建和编辑新版文档 | 必需 |
| `drive:drive` | 云空间文件 | 上传图片、管理文件 | 必需 |
| `drive:drive:readonly` | 云空间文件（只读） | 列出文件夹内容、检测重复 | 必需 |
| `wiki:wiki` | 知识库 | 在知识库中创建和编辑文档 | 写入知识库时必需 |

JSON 格式权限列表（便于程序化配置）：

```json
[
  {
    "scope": "docx:document",
    "description": "查看、创建、编辑和管理云空间中的新版文档",
    "required": true
  },
  {
    "scope": "drive:drive",
    "description": "查看、创建、编辑和管理云空间中的文件",
    "required": true
  },
  {
    "scope": "drive:drive:readonly",
    "description": "查看云空间中的文件",
    "required": true
  },
  {
    "scope": "wiki:wiki",
    "description": "查看、创建、编辑和管理知识库",
    "required": true,
    "note": "写入知识库时必需"
  }
]
```

**重要**：权限开通后，需要 **创建应用版本并发布** 才能生效：

1. 进入 **「版本管理与发布」**
2. 点击 **「创建版本」**
3. 填写版本号和更新说明
4. 提交审核（企业管理员审批后生效）

## 3. 配置环境变量

将项目根目录下的 `.env.example` 复制为 `.env`，填入实际凭证：

```dotenv
# 必需：飞书应用凭证
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx

# 可选：默认知识库配置
# 配置后可直接使用 --target wiki 而无需每次指定 --wiki-token
# FEISHU_DEFAULT_WIKI_NODE_TOKEN=你的知识库node_token
# FEISHU_DEFAULT_WIKI_SPACE_ID=你的知识库space_id（可自动通过node_token查询）

# 可选：默认文件夹配置
# 配置后可直接使用 --target folder 而无需每次指定 --folder-token
# FEISHU_DEFAULT_FOLDER_TOKEN=你的文件夹folder_token
```

各变量说明：

| 变量名 | 是否必需 | 说明 |
|--------|---------|------|
| `FEISHU_APP_ID` | 必需 | 飞书应用的 App ID |
| `FEISHU_APP_SECRET` | 必需 | 飞书应用的 App Secret |
| `FEISHU_DEFAULT_WIKI_NODE_TOKEN` | 可选 | 默认知识库节点 token，配置后 `--target wiki` 无需再传 `--wiki-token` |
| `FEISHU_DEFAULT_WIKI_SPACE_ID` | 可选 | 默认知识库 space_id，程序可自动通过 node_token 查询 |
| `FEISHU_DEFAULT_FOLDER_TOKEN` | 可选 | 默认云空间文件夹 token，配置后 `--target folder` 无需再传 `--folder-token` |

> **注意**：仅配置 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 时，只能使用默认的 `--target space` 模式。该模式下文档会创建在应用自身的云空间中，飞书客户端无法直接浏览，只能通过程序输出的链接访问。建议配置知识库或文件夹的默认 token。

## 4. 添加应用为协作者

应用必须被添加为目标文档/知识库的协作者才能写入内容。这一步最容易遗漏。

### 4.1 云空间文件夹（通过群组中介）

云空间文件夹**不支持**直接添加文档应用。飞书应用的机器人账号无法直接在 Web 页面登录或发起授权申请，因此需要借助一个群组作为中介，将应用机器人加入群，再把文件夹分享给该群。

操作步骤：

1. 在飞书中**新建一个群组**（专门用于授权，群名随意，如"文档权限授权群"）
2. 进入该群的设置，找到 **「机器人」** 选项，点击 **「添加机器人」**，搜索并添加你创建的应用对应的机器人
3. 打开飞书**云文档 > 我的空间**，找到目标文件夹
4. 点击文件夹右侧的 **「分享」** 按钮
5. 在协作者搜索框中搜索刚才新建的**群组名称**
6. 将该群组添加为协作者，分配 **「可编辑」** 权限

完成后，应用机器人通过"群成员"身份获得该文件夹的访问权限。

### 4.2 知识库

1. 打开目标知识库页面
2. 点击右上角 **「···」** 图标
3. 选择 **「更多」** > **「添加文档应用」**
4. 搜索你创建的应用名称
5. 为应用分配 **「可编辑」** 权限
6. 点击 **「添加」**

> **注意**：只有知识库的所有者或拥有 **「可管理」** 权限的协作者才能添加应用。如果看不到「添加文档应用」选项，请联系知识库管理员。

### 4.3 验证权限

添加成功后，应用将出现在协作者列表中。可以通过运行一个简单的写入测试来验证：

```bash
# 创建测试文件
echo "# 测试文档" > test.md

# 尝试写入
python -m scripts.feishu_writer test.md --target wiki
```

如果返回成功，说明权限配置正确。
