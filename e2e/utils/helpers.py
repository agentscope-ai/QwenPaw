# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试框架 - 工具函数

提供通用的测试辅助函数。
"""
from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Any, Dict, List
from datetime import datetime
from playwright.sync_api import Page, Locator, APIRequestContext

from config.settings import config


logger = logging.getLogger(__name__)


# ============================================================================
# 截图和录制
# ============================================================================

def take_screenshot(page: Page, name: str, full_page: bool = True) -> str:
    """
    截取屏幕截图
    
    Args:
        page: Playwright Page 实例
        name: 截图名称
        full_page: 是否截取完整页面
        
    Returns:
        截图文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}.png"
    path = config.paths.screenshots_dir / filename
    
    page.screenshot(path=str(path), full_page=full_page)
    logger.info(f"Screenshot saved: {path}")
    return str(path)


def save_video(page: Page, name: str) -> Optional[str]:
    """
    保存录制视频
    
    Args:
        page: Playwright Page 实例
        name: 视频名称
        
    Returns:
        视频文件路径或 None
    """
    if not page.video:
        logger.warning("Video recording not enabled")
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}.webm"
    path = config.paths.videos_dir / filename
    
    page.video.save_as(str(path))
    logger.info(f"Video saved: {path}")
    return str(path)


# ============================================================================
# API 辅助函数
# ============================================================================

def api_get(api_context: APIRequestContext, endpoint: str, params: Optional[Dict] = None) -> Dict:
    """
    发送 GET 请求
    
    Args:
        api_context: API 请求上下文
        endpoint: API 端点
        params: 查询参数
        
    Returns:
        响应 JSON
    """
    # endpoint already includes path, api_context has base_url
    logger.info(f"GET {endpoint}")
    
    response = api_context.get(endpoint, params=params)
    assert response.ok, f"API request failed: {response.status} {response.status_text}"
    
    return response.json()


def api_post(api_context: APIRequestContext, endpoint: str, data: Optional[Dict] = None) -> Dict:
    """
    发送 POST 请求
    
    Args:
        api_context: API 请求上下文
        endpoint: API 端点
        data: 请求数据
        
    Returns:
        响应 JSON
    """
    # endpoint already includes path, api_context has base_url
    logger.info(f"POST {endpoint}, data: {data}")
    
    response = api_context.post(endpoint, data=data)
    assert response.ok, f"API request failed: {response.status} {response.status_text}"
    
    return response.json()


def api_delete(api_context: APIRequestContext, endpoint: str) -> Dict:
    """
    发送 DELETE 请求
    
    Args:
        api_context: API 请求上下文
        endpoint: API 端点
        
    Returns:
        响应 JSON
    """
    logger.info(f"DELETE {endpoint}")
    
    response = api_context.delete(endpoint)
    assert response.ok, f"DELETE {endpoint} failed: {response.status} {response.status_text}"
    
    return response.json()


# ============================================================================
# 等待和重试
# ============================================================================

def wait_for_condition(condition_func, timeout: int = 30000, interval: int = 500) -> Any:
    """
    等待条件满足
    
    Args:
        condition_func: 条件函数，返回 Truthy 值表示成功
        timeout: 超时时间（毫秒）
        interval: 检查间隔（毫秒）
        
    Returns:
        条件函数的返回值
        
    Raises:
        TimeoutError: 超时
    """
    start_time = time.time()
    timeout_sec = timeout / 1000
    
    while time.time() - start_time < timeout_sec:
        result = condition_func()
        if result:
            logger.debug(f"Condition met after {time.time() - start_time:.2f}s")
            return result
        
        time.sleep(interval / 1000)
    
    raise TimeoutError(f"Condition not met within {timeout}ms")


def retry_operation(operation_func, max_retries: int = 3, delay: float = 1.0) -> Any:
    """
    重试操作
    
    Args:
        operation_func: 操作函数
        max_retries: 最大重试次数
        delay: 重试间隔（秒）
        
    Returns:
        操作结果
        
    Raises:
        Exception: 所有重试都失败
    """
    if max_retries <= 0:
        raise ValueError(f"max_retries must be positive, got {max_retries}")
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return operation_func()
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(delay)
    
    raise last_exception


# ============================================================================
# 文件操作
# ============================================================================

def create_test_file(tmp_path: Path, filename: str, content: str) -> Path:
    """
    创建测试文件
    
    Args:
        tmp_path: 临时目录
        filename: 文件名
        content: 文件内容
        
    Returns:
        文件路径
    """
    file_path = tmp_path / filename
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Test file created: {file_path}")
    return file_path


def read_test_data(filename: str) -> str:
    """
    读取测试数据文件
    
    Args:
        filename: 文件名
        
    Returns:
        文件内容
    """
    file_path = config.paths.data_dir / filename
    
    if not file_path.exists():
        raise FileNotFoundError(f"Test data file not found: {file_path}")
    
    return file_path.read_text(encoding="utf-8")


def load_json_data(filename: str) -> Dict:
    """
    加载 JSON 测试数据
    
    Args:
        filename: 文件名
        
    Returns:
        JSON 数据
    """
    content = read_test_data(filename)
    return json.loads(content)


# ============================================================================
# 断言辅助
# ============================================================================

def assert_element_visible(page: Page, selector: str, timeout: int = 5000) -> bool:
    """
    断言元素可见
    
    Args:
        page: Playwright Page 实例
        selector: CSS 选择器
        timeout: 超时时间
        
    Returns:
        是否可见
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        return True
    except Exception as e:
        logger.debug(f"Element not visible: {selector}, error: {e}")
        return False


def assert_text_contains(page: Page, selector: str, expected_text: str, timeout: int = 5000) -> bool:
    """
    断言文本包含
    
    Args:
        page: Playwright Page 实例
        selector: CSS 选择器
        expected_text: 期望文本
        timeout: 超时时间
        
    Returns:
        是否包含
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        text = locator.inner_text()
        return expected_text.lower() in text.lower()
    except Exception as e:
        logger.debug(f"Text assertion failed: {e}")
        return False


def assert_count(page: Page, selector: str, expected_count: int, timeout: int = 5000) -> bool:
    """
    断言元素数量
    
    Args:
        page: Playwright Page 实例
        selector: CSS 选择器
        expected_count: 期望数量
        timeout: 超时时间
        
    Returns:
        是否匹配
    """
    try:
        locator = page.locator(selector)
        locator.first.wait_for(state="attached", timeout=timeout)
        actual_count = locator.count()
        return actual_count == expected_count
    except Exception as e:
        logger.debug(f"Count assertion failed: {e}")
        return False


# ============================================================================
# 日志和报告
# ============================================================================

def log_test_step(step_name: str, details: Optional[str] = None):
    """
    记录测试步骤
    
    Args:
        step_name: 步骤名称
        details: 详细信息
    """
    logger.info(f"STEP: {step_name}")
    if details:
        logger.info(f"  Details: {details}")


def log_test_result(test_name: str, status: str, message: str):
    """
    记录测试结果
    
    Args:
        test_name: 测试名称
        status: 测试状态 ("PASS"/"FAIL"/"SKIP")
        message: 描述信息
    """
    logger.info(f"TEST: {test_name} - {status} - {message}")


def generate_test_summary(results: List[Dict]) -> str:
    """
    生成测试摘要
    
    Args:
        results: 测试结果列表
        
    Returns:
        摘要文本
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0.0
    
    summary = f"""
{'='*60}
测试摘要
{'='*60}
总计：{total}
通过：{passed}
失败：{failed}
通过率：{pass_rate:.1f}%
{'='*60}
"""
    
    if failed > 0:
        summary += "\n失败的测试:\n"
        for r in results:
            if not r.get("passed", False):
                summary += f"  - {r.get('name', 'Unknown')}: {r.get('error', 'Unknown error')}\n"
    
    return summary


# ============================================================================
# 其他工具
# ============================================================================

def generate_unique_id(prefix: str = "test") -> str:
    """
    生成唯一 ID
    
    Args:
        prefix: 前缀
        
    Returns:
        唯一 ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{timestamp}"


def sanitize_filename(filename: str) -> str:
    """
    清理文件名（移除非法字符）
    
    Args:
        filename: 原始文件名
        
    Returns:
        清理后的文件名
    """
    illegal_chars = '<>:"/\\|？*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    return filename


def get_env_bool(env_var: str, default: bool = False) -> bool:
    """
    从环境变量获取布尔值
    
    Args:
        env_var: 环境变量名
        default: 默认值
        
    Returns:
        布尔值
    """
    value = os.getenv(env_var, str(default)).lower()
    return value in ("true", "1", "yes")
