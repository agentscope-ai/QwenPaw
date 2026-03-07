# -*- coding: utf-8 -*-
"""
Streaming AI skill optimization API
"""
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import json

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
description: Query weather information for a specified city, returns temperature, humidity, wind data
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

    "ru": """Вы эксперт по оптимизации AI-навыков. Пожалуйста, оптимизируйте следующее содержимое навыка.

## Требования к формату вывода
Выводите содержимое навыка напрямую. НЕ используйте маркеры блока кода (например, ```yaml или ```). НЕ добавляйте никаких объяснений.

## Правила оптимизации
1. Сохраните структуру frontmatter (раздел заголовка, заключённый в ---)
2. Поле name: строчные буквы с подчёркиванием
3. Поле description: чёткое и краткое, не более 80 символов
4. Основное содержимое: используйте формат Markdown, структурировано
5. Общая длина: не более 500 символов

## Пример вывода
---
name: weather_query
description: Запрос информации о погоде для указанного города, возвращает температуру, влажность, данные о ветре
---

## Функции
Запрос данных о погоде в реальном времени.

## Использование
Пользователь вводит название города, возвращается информация о погоде.

---
Пожалуйста, оптимизируйте этот навык:"""
}


class AIOptimizeSkillRequest(BaseModel):
    content: str = Field(..., description="Current skill content to optimize")
    language: str = Field(default="en", description="Language for optimization (en, zh, ru)")


router = APIRouter(tags=["skills"])


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
                error_msg = json.dumps({"error": "No AI model configured. Please configure a model in Settings first."})
                yield f"data: {error_msg}\n\n"
                return

            # Get system prompt for the requested language
            system_prompt = SYSTEM_PROMPTS.get(request.language, SYSTEM_PROMPTS["en"])

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.content},
            ]

            response = await model(messages)
            
            # Track accumulated text to send only deltas
            accumulated = ""
            
            # Stream the response
            if hasattr(response, "__aiter__"):
                async for chunk in response:
                    if hasattr(chunk, "content"):
                        text = ""
                        if isinstance(chunk.content, list):
                            for item in chunk.content:
                                if isinstance(item, dict) and 'text' in item:
                                    text = item['text']
                                    break
                        elif isinstance(chunk.content, str):
                            text = chunk.content
                        
                        if text and len(text) > len(accumulated):
                            # Send only the new part (delta)
                            delta = text[len(accumulated):]
                            accumulated = text
                            data = json.dumps({"text": delta}, ensure_ascii=False)
                            yield f"data: {data}\n\n"
            else:
                # Fallback for non-streaming response
                text = ""
                if hasattr(response, "text"):
                    text = response.text
                elif isinstance(response, str):
                    text = response
                    
                if text:
                    data = json.dumps({"text": text}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    
            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            logger.exception("AI skill optimization failed: %s", e)
            error_msg = json.dumps({"error": f"Failed to optimize skill: {str(e)}"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
