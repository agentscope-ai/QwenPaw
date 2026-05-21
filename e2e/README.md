# QwenPaw E2E 测试框架

专业的端到端测试框架，基于 Playwright + pytest + Page Object Pattern。

## 📁 目录结构

```
tests/
├── config/                 # 配置模块
│   ├── __init__.py
│   └── settings.py         # 统一配置管理
├── pages/                  # Page Object 层
│   ├── __init__.py
│   ├── base_page.py        # 页面对象基类
│   └── chat_page.py        # Chat 页面对象
├── fixtures/               # Pytest Fixtures
│   └── __init__.py         # 浏览器、页面、API 等 fixture
├── utils/                  # 工具函数
│   ├── __init__.py
│   └── helpers.py          # 辅助函数
├── tests/                  # 测试用例
│   └── test_chat_p0.py     # Chat P0 测试用例
├── data/                   # 测试数据
├── reports/                # 测试报告（自动生成）
│   ├── screenshots/        # 截图
│   ├── videos/             # 录制视频
│   ├── logs/               # 日志
│   └── allure-results/     # Allure 报告
├── conftest.py             # Pytest 配置
├── pytest.ini              # Pytest 配置文件
└── requirements.txt        # 依赖列表
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd /Users/ming/.qwenpaw/workspaces/Hv3HJ9
pip install -r tests/requirements.txt
playwright install chromium
```

### 2. 确保 QwenPaw 服务运行

```bash
qwenpaw start
# 或
cd /Users/ming/Desktop/qwenpaw && python -m qwenpaw
```

### 3. 运行测试

```bash
# 运行所有 P0 测试
pytest tests/tests/test_chat_p0.py -v

# 运行特定测试类
pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA -v

# 运行特定测试用例
pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA::test_new_chat_basic_qa_copy -v

# 按标记运行
pytest tests/tests/test_chat_p0.py -m "chat_core" -v
pytest tests/tests/test_chat_p0.py -m "chat_file" -v
```

### 4. 有头模式（可视化调试）

```bash
QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py -v
```

### 5. 慢动作模式（调试用）

```bash
PLAYWRIGHT_SLOW_MO=1000 pytest tests/tests/test_chat_p0.py -v
```

## 📋 测试用例列表

### P0 级别测试（核心功能）

| 测试类 | 测试用例 | 覆盖功能点 | 优先级 |
|--------|---------|-----------|--------|
| **TestNewChatAndBasicQA** | test_new_chat_basic_qa_copy | 新建对话、基础问答、消息复制 | P0 |
| **TestMultiTurnConversation** | test_multi_turn_context_awareness | 多轮对话、上下文理解 | P0 |
| **TestFileUploadAndQA** | test_upload_file_and_ask_questions | 文件上传、基于文件问答 | P0 |
| **TestSessionManagement** | test_session_rename_pin_delete_switch | 会话管理完整流程 | P0 |
| **TestAdvancedFeatures** | test_model_switch_and_skill_invocation | 模型切换、技能调用 | P0 |
| **TestInputValidationAndEdgeCases** | test_input_validation_and_special_chars | 特殊字符、代码块输入 | P0 |

## 🔧 配置选项

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `QWENPAW_BASE_URL` | `http://localhost:8088` | QwenPaw 服务地址 |
| `QWENPAW_HEADLESS` | `true` | 是否无头模式 (`true`/`false`) |
| `QWENPAW_TIMEOUT` | `30000` | 超时时间（毫秒） |
| `QWENPAW_USER_ID` | `default` | 用户 ID |
| `QWENPAW_CHANNEL` | `console` | 频道名称 |
| `PLAYWRIGHT_SLOW_MO` | `0` | 慢动作时间（毫秒） |

### 使用示例

```bash
# 指定服务地址
QWENPAW_BASE_URL=http://127.0.0.1:9000 pytest tests/tests/test_chat_p0.py -v

# 有头模式 + 慢动作
QWENPAW_HEADLESS=false PLAYWRIGHT_SLOW_MO=500 pytest tests/tests/test_chat_p0.py -v

# 增加超时时间
QWENPAW_TIMEOUT=60000 pytest tests/tests/test_chat_p0.py -v
```

## 📊 测试报告

### HTML 报告

```bash
pytest tests/tests/test_chat_p0.py --html=reports/test_report.html --self-contained-html
```

### Allure 报告

```bash
# 生成报告
pytest tests/tests/test_chat_p0.py --alluredir=reports/allure-results

# 查看报告
allure serve reports/allure-results
```

### 日志文件

测试日志保存在 `reports/logs/` 目录下。

## 🏗️ 框架架构

### Page Object Pattern

```
┌─────────────────────────────────────┐
│           Test Cases                │
│      (tests/test_chat_p0.py)        │
├─────────────────────────────────────┤
│         Page Objects                │
│    (pages/chat_page.py)             │
│  - 业务级别方法                      │
│  - 封装页面操作                      │
├─────────────────────────────────────┤
│         Base Page                   │
│    (pages/base_page.py)             │
│  - 通用页面操作                      │
│  - 元素查找/等待/断言                │
├─────────────────────────────────────┤
│         Playwright API              │
└─────────────────────────────────────┘
```

### ChatPage 主要方法

```python
# 导航
chat_page.open()                      # 打开 Chat 页面
chat_page.create_new_chat()           # 新建对话

# 消息操作
chat_page.send_message("你好")         # 发送消息
chat_page.send_message_and_wait("你好") # 发送并等待回复
chat_page.wait_for_ai_response()      # 等待 AI 回复
chat_page.copy_last_message()         # 复制消息

# 文件上传
chat_page.upload_file("/path/to/file") # 上传文件
chat_page.verify_file_uploaded()      # 验证上传成功

# 会话管理
chat_page.open_session_list()         # 打开会话列表
chat_page.rename_session(0, "新名称")  # 重命名会话
chat_page.pin_session(1)              # 置顶会话
chat_page.delete_session(0)           # 删除会话
chat_page.switch_to_session(0)        # 切换会话

# 模型和技能
chat_page.select_model("gpt-4")       # 选择模型
chat_page.invoke_skill("skills")      # 调用技能
chat_page.expand_tool_details()       # 展开工具详情

# 断言
chat_page.verify_welcome_screen()     # 验证欢迎界面
chat_page.get_session_count()         # 获取会话数量
chat_page.has_error()                 # 检查错误
```

## 📝 编写新测试

### 基本模板

```python
import pytest
from pages.chat_page import ChatPage

@pytest.mark.p0
@pytest.mark.chat_core
class TestNewFeature:
    """新功能测试"""

    @pytest.mark.test_id("P0-XXX")
    def test_feature_name(self, chat_page: ChatPage, request: pytest.FixtureRequest):
        """测试描述"""
        test_name = request.node.name

        # Step 1: 访问页面
        chat_page.open()

        # Step 2: 执行操作
        chat_page.send_message("测试消息")

        # Step 3: 验证结果
        ai_message = chat_page.wait_for_ai_response()
        assert ai_message is not None

        # Step 4: 记录结果
        logger.info(f"✅ Test {test_name} passed")
```

### 使用参数化

```python
@pytest.mark.parametrize("message,expected_keyword", [
    ("你好", "你好"),
    ("你是谁？", "介绍"),
    ("帮助", "帮助"),
])
def test_various_messages(self, chat_page, message, expected_keyword):
    chat_page.open()
    chat_page.send_message_and_wait(message)

    ai_msg = chat_page.get_last_ai_message()
    assert chat_page.verify_message_contains(ai_msg, expected_keyword)
```

## 🐛 常见问题

### 1. 测试失败：无法连接到 QwenPaw 服务

```bash
# 检查服务状态
qwenpaw status

# 手动启动
cd /Users/ming/Desktop/qwenpaw && python -m qwenpaw
```

### 2. 测试失败：元素找不到

```bash
# 使用有头模式调试
QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA -v

# 增加超时
QWENPAW_TIMEOUT=60000 pytest tests/tests/test_chat_p0.py -v

# 使用慢动作查看页面加载
PLAYWRIGHT_SLOW_MO=1000 QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py -v
```

### 3. 浏览器启动失败

```bash
# 重新安装浏览器
playwright install chromium

# 检查依赖
playwright install-deps chromium
```

### 4. 测试报告不生成

```bash
# 确保目录存在
mkdir -p tests/reports

# 检查权限
chmod 755 tests/reports
```

## 🔬 高级用法

### 并行执行

```bash
# 使用 4 个 worker 并行执行
pytest tests/tests/test_chat_p0.py -n 4 -v
```

### 失败重试

```bash
# 失败后重试 2 次
pytest tests/tests/test_chat_p0.py --reruns 2 -v
```

### 覆盖率报告

```bash
pytest tests/tests/test_chat_p0.py --cov=src --cov-report=html -v
```

### 生成测试数据

```python
from faker import Faker

fake = Faker("zh_CN")

def test_with_generated_data(self, chat_page):
    chat_page.open()
    chat_page.send_message(fake.sentence())
    chat_page.wait_for_ai_response()
```

## 📚 相关文档

- [Playwright 文档](https://playwright.dev/python/)
- [pytest 文档](https://docs.pytest.org/)
- [Page Object Pattern](https://playwright.dev/python/docs/test-pom)
- [Allure 报告](https://docs.qameta.io/allure/)

## 👥 维护者

- QA Assistant
- 最后更新：2026-04-13
