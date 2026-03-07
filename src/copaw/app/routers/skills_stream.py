# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""
Streaming AI skill optimization API
"""
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...agents.model_factory import create_model_and_formatter


logger = logging.getLogger(__name__)


def get_model():
    """Get the active chat model instance.

    Returns:
        Chat model instance or None if not configured
    """
    try:
        model, _ = create_model_and_formatter()
        return model
    except Exception as e:
        logger.warning("Failed to get model: %s", e)
        return None


# System prompts for different languages
SYSTEM_PROMPTS = {
    "en": """You are an AI skill optimization expert. Please optimize the following skill content.

## Output Format Requirements
Output the skill content directly. Do NOT use code block markers (like ```yaml or ```). Do NOT add any explanations.

## Optimization Rules
1. Keep the frontmatter structure (--- enclosed header section)
2. name field: lowercase with underscores
3. description field: clear and concise, no more than 80 characters
4. Body content: use Markdown format, well-structured
5. Total length: keep within 500 characters

## Example Output
---
name: weather_query
description: Query weather info for a city, returns temperature, humidity, wind
---

## Features
Query real-time weather data.

## Usage
User inputs city name, returns weather information.

---
Please optimize this skill:""",
    "zh": """你是AI技能优化专家。请优化以下技能内容。

## 输出格式要求
直接输出技能内容，禁止使用代码块标记（如 ```yaml 或 ```），禁止添加任何解释说明。

## 优化规则
1. 保持frontmatter结构（--- 包围的头部区域）
2. name字段：英文小写下划线命名
3. description字段：简洁清晰，不超过80字
4. 正文用Markdown格式，结构清晰
5. 总长度控制在500字以内

## 示例输出
---
name: weather_query
description: 查询指定城市天气信息，返回温度、湿度、风力等数据
---

## 功能
查询实时天气数据。

## 使用
输入城市名，返回天气信息。

---
请优化此技能:""",
    "ru": """Вы эксперт по оптимизации AI-навыков. Пожалуйста, оптимизируйте навык.

## Требования к формату вывода
Выводите содержимое навыка напрямую. НЕ используйте маркеры блока кода.

## Правила оптимизации
1. Сохраните структуру frontmatter (раздел заголовка, заключённый в ---)
2. Поле name: строчные буквы с подчёркиванием
3. Поле description: чёткое и краткое, не более 80 символов
4. Основное содержимое: используйте формат Markdown
5. Общая длина: не более 500 символов

## Пример вывода
---
name: weather_query
description: Запрос погоды для города, возвращает температуру и влажность
---

## Функции
Запрос данных о погоде в реальном времени.

## Использование
Пользователь вводит город, возвращается информация о погоде.

---
Пожалуйста, оптимизируйте этот навык:""",
}


class AIOptimizeSkillRequest(BaseModel):
    content: str = Field(..., description="Current skill content to optimize")
    language: str = Field(
        default="en",
        description="Language for optimization (en, zh, ru)",
    )


router = APIRouter(tags=["skills"])


def _extract_text_from_chunk(chunk) -> str:
    """Extract text content from a response chunk.

    Args:
        chunk: Response chunk from the model

    Returns:
        Extracted text string or empty string
    """
    if not hasattr(chunk, "content"):
        return ""

    if isinstance(chunk.content, str):
        return chunk.content

    if isinstance(chunk.content, list):
        for item in chunk.content:
            if isinstance(item, dict) and "text" in item:
                return item["text"]

    return ""


def _extract_text_from_response(response) -> str:
    """Extract text from a non-streaming response.

    Args:
        response: Non-streaming response from the model

    Returns:
        Extracted text string or empty string
    """
    if hasattr(response, "text"):
        return response.text
    if isinstance(response, str):
        return response
    return ""


@router.post("/skills/ai/optimize/stream")
async def ai_optimize_skill_stream(request: AIOptimizeSkillRequest):
    """Use AI to optimize an existing skill with streaming response.

    Args:
        request: Contains current skill content and language preference

    Returns:
        StreamingResponse with optimized skill content (text deltas)
    """

    async def generate():
        try:
            model = get_model()
            if not model:
                error_msg = json.dumps(
                    {
                        "error": (
                            "No AI model configured. "
                            "Please configure in Settings."
                        ),
                    },
                )
                yield f"data: {error_msg}\n\n"
                return

            system_prompt = SYSTEM_PROMPTS.get(
                request.language,
                SYSTEM_PROMPTS["en"],
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.content},
            ]

            response = await model(messages)
            accumulated = ""

            if hasattr(response, "__aiter__"):
                async for chunk in response:
                    text = _extract_text_from_chunk(chunk)

                    if text and len(text) > len(accumulated):
                        delta = text[len(accumulated) :]
                        accumulated = text
                        data = json.dumps(
                            {"text": delta},
                            ensure_ascii=False,
                        )
                        yield f"data: {data}\n\n"
            else:
                text = _extract_text_from_response(response)
                if text:
                    data = json.dumps(
                        {"text": text},
                        ensure_ascii=False,
                    )
                    yield f"data: {data}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            logger.exception("AI skill optimization failed: %s", e)
            error_msg = json.dumps(
                {"error": f"Failed to optimize skill: {str(e)}"},
                ensure_ascii=False,
            )
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
