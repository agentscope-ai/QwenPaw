# QwenPaw E2E Test Framework

End-to-end test framework built on Playwright + pytest + the Page Object Pattern.

## Directory Layout

```
tests/
├── config/                 # Configuration module
│   ├── __init__.py
│   └── settings.py         # Unified config management
├── pages/                  # Page Object layer
│   ├── __init__.py
│   ├── base_page.py        # Base page class
│   └── chat_page.py        # Chat page object
├── fixtures/               # Pytest fixtures
│   └── __init__.py         # Browser, page, API fixtures
├── utils/                  # Utility functions
│   ├── __init__.py
│   └── helpers.py          # Helper functions
├── tests/                  # Test cases
│   └── test_chat_p0.py     # Chat P0 test cases
├── data/                   # Test data
├── reports/                # Test reports (auto-generated)
│   ├── screenshots/        # Screenshots
│   ├── videos/             # Recorded videos
│   ├── logs/               # Logs
│   └── allure-results/     # Allure reports
├── conftest.py             # Pytest configuration
├── pytest.ini              # Pytest configuration file
└── requirements.txt        # Dependency list
```

## Quick Start

### 1. Install dependencies

```bash
cd /Users/ming/.qwenpaw/workspaces/Hv3HJ9
pip install -r tests/requirements.txt
playwright install chromium
```

### 2. Ensure the QwenPaw service is running

```bash
qwenpaw start
# or
cd /Users/ming/Desktop/qwenpaw && python -m qwenpaw
```

### 3. Run tests

```bash
# Run all P0 tests
pytest tests/tests/test_chat_p0.py -v

# Run a specific test class
pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA -v

# Run a specific test case
pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA::test_new_chat_basic_qa_copy -v

# Run by marker
pytest tests/tests/test_chat_p0.py -m "chat_core" -v
pytest tests/tests/test_chat_p0.py -m "chat_file" -v
```

### 4. Headed mode (visual debugging)

```bash
QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py -v
```

### 5. Slow-motion mode (for debugging)

```bash
PLAYWRIGHT_SLOW_MO=1000 pytest tests/tests/test_chat_p0.py -v
```

## Test Case List

### P0 tests (core functionality)

| Test Class | Test Case | Feature Coverage | Priority |
|------------|-----------|------------------|----------|
| **TestNewChatAndBasicQA** | test_new_chat_basic_qa_copy | New chat, basic Q&A, message copy | P0 |
| **TestMultiTurnConversation** | test_multi_turn_context_awareness | Multi-turn dialogue, context understanding | P0 |
| **TestFileUploadAndQA** | test_upload_file_and_ask_questions | File upload, Q&A based on file | P0 |
| **TestSessionManagement** | test_session_rename_pin_delete_switch | End-to-end session management | P0 |
| **TestAdvancedFeatures** | test_model_switch_and_skill_invocation | Model switching, skill invocation | P0 |
| **TestInputValidationAndEdgeCases** | test_input_validation_and_special_chars | Special characters, code-block input | P0 |

## Configuration Options

### Environment variables

| Name | Default | Description |
|------|---------|-------------|
| `QWENPAW_BASE_URL` | `http://localhost:8088` | QwenPaw service URL |
| `QWENPAW_HEADLESS` | `true` | Headless mode (`true`/`false`) |
| `QWENPAW_TIMEOUT` | `30000` | Timeout (milliseconds) |
| `QWENPAW_USER_ID` | `default` | User ID |
| `QWENPAW_CHANNEL` | `console` | Channel name |
| `PLAYWRIGHT_SLOW_MO` | `0` | Slow-motion delay (milliseconds) |

### Examples

```bash
# Override the service URL
QWENPAW_BASE_URL=http://127.0.0.1:9000 pytest tests/tests/test_chat_p0.py -v

# Headed mode + slow motion
QWENPAW_HEADLESS=false PLAYWRIGHT_SLOW_MO=500 pytest tests/tests/test_chat_p0.py -v

# Increase timeout
QWENPAW_TIMEOUT=60000 pytest tests/tests/test_chat_p0.py -v
```

## Test Reports

### HTML report

```bash
pytest tests/tests/test_chat_p0.py --html=reports/test_report.html --self-contained-html
```

### Allure report

```bash
# Generate report
pytest tests/tests/test_chat_p0.py --alluredir=reports/allure-results

# View report
allure serve reports/allure-results
```

### Log files

Test logs are saved under `reports/logs/`.

## Framework Architecture

### Page Object Pattern

```
┌─────────────────────────────────────┐
│           Test Cases                │
│      (tests/test_chat_p0.py)        │
├─────────────────────────────────────┤
│         Page Objects                │
│    (pages/chat_page.py)             │
│  - Business-level methods           │
│  - Encapsulated page operations     │
├─────────────────────────────────────┤
│         Base Page                   │
│    (pages/base_page.py)             │
│  - Generic page operations          │
│  - Element find/wait/assert         │
├─────────────────────────────────────┤
│         Playwright API              │
└─────────────────────────────────────┘
```

### Main ChatPage methods

```python
# Navigation
chat_page.open()                      # Open the Chat page
chat_page.create_new_chat()           # Start a new chat

# Message operations
chat_page.send_message("hello")              # Send a message
chat_page.send_message_and_wait("hello")     # Send and wait for reply
chat_page.wait_for_ai_response()      # Wait for the AI reply
chat_page.copy_last_message()         # Copy the message

# File upload
chat_page.upload_file("/path/to/file") # Upload a file
chat_page.verify_file_uploaded()      # Verify upload succeeded

# Session management
chat_page.open_session_list()         # Open the session list
chat_page.rename_session(0, "new name")  # Rename a session
chat_page.pin_session(1)              # Pin a session
chat_page.delete_session(0)           # Delete a session
chat_page.switch_to_session(0)        # Switch session

# Models and skills
chat_page.select_model("gpt-4")       # Select model
chat_page.invoke_skill("skills")      # Invoke skill
chat_page.expand_tool_details()       # Expand tool details

# Assertions
chat_page.verify_welcome_screen()     # Verify the welcome screen
chat_page.get_session_count()         # Get the session count
chat_page.has_error()                 # Check for errors
```

## Writing New Tests

### Basic template

```python
import pytest
from pages.chat_page import ChatPage

@pytest.mark.p0
@pytest.mark.chat_core
class TestNewFeature:
    """New feature tests"""

    @pytest.mark.test_id("P0-XXX")
    def test_feature_name(self, chat_page: ChatPage, request: pytest.FixtureRequest):
        """Test description"""
        test_name = request.node.name

        # Step 1: Visit the page
        chat_page.open()

        # Step 2: Perform actions
        chat_page.send_message("test message")

        # Step 3: Verify the result
        ai_message = chat_page.wait_for_ai_response()
        assert ai_message is not None

        # Step 4: Log the result
        logger.info(f"Test {test_name} passed")
```

### Parametrized tests

```python
@pytest.mark.parametrize("message,expected_keyword", [
    ("hello", "hello"),
    ("who are you?", "introduce"),
    ("help", "help"),
])
def test_various_messages(self, chat_page, message, expected_keyword):
    chat_page.open()
    chat_page.send_message_and_wait(message)

    ai_msg = chat_page.get_last_ai_message()
    assert chat_page.verify_message_contains(ai_msg, expected_keyword)
```

## FAQ

### 1. Test failure: cannot connect to the QwenPaw service

```bash
# Check service status
qwenpaw status

# Start manually
cd /Users/ming/Desktop/qwenpaw && python -m qwenpaw
```

### 2. Test failure: element not found

```bash
# Debug in headed mode
QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py::TestNewChatAndBasicQA -v

# Increase timeout
QWENPAW_TIMEOUT=60000 pytest tests/tests/test_chat_p0.py -v

# Use slow motion to inspect page loading
PLAYWRIGHT_SLOW_MO=1000 QWENPAW_HEADLESS=false pytest tests/tests/test_chat_p0.py -v
```

### 3. Browser fails to launch

```bash
# Reinstall the browser
playwright install chromium

# Check dependencies
playwright install-deps chromium
```

### 4. Test report is not generated

```bash
# Make sure the directory exists
mkdir -p tests/reports

# Check permissions
chmod 755 tests/reports
```

## Advanced Usage

### Parallel execution

```bash
# Run with 4 workers in parallel
pytest tests/tests/test_chat_p0.py -n 4 -v
```

### Retry on failure

```bash
# Retry twice on failure
pytest tests/tests/test_chat_p0.py --reruns 2 -v
```

### Coverage report

```bash
pytest tests/tests/test_chat_p0.py --cov=src --cov-report=html -v
```

### Generate test data

```python
from faker import Faker

fake = Faker("en_US")

def test_with_generated_data(self, chat_page):
    chat_page.open()
    chat_page.send_message(fake.sentence())
    chat_page.wait_for_ai_response()
```

## References

- [Playwright docs](https://playwright.dev/python/)
- [pytest docs](https://docs.pytest.org/)
- [Page Object Pattern](https://playwright.dev/python/docs/test-pom)
- [Allure reports](https://docs.qameta.io/allure/)

## Maintainers

- QA Assistant
- Last updated: 2026-04-13
