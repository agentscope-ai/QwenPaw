#!/usr/bin/env python3
"""
本地 Embedding 服务 - OpenAI 兼容接口
使用 fastembed + ONNX，无需 GPU，无需外部 API
默认监听 http://127.0.0.1:18089
"""

import asyncio
import logging
import time
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Local Embedding Server")

# 全局模型实例
_model = None
MODEL_NAME = "BAAI/bge-small-zh-v1.5"  # 中文优化，384维，~90MB


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        logger.info(f"加载模型: {MODEL_NAME}")
        _model = TextEmbedding(model_name=MODEL_NAME)
        logger.info("模型就绪")
    return _model


class EmbeddingRequest(BaseModel):
    input: List[str] | str
    model: Optional[str] = MODEL_NAME
    encoding_format: Optional[str] = "float"


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: dict


@app.on_event("startup")
async def startup():
    """预加载模型"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_model)
    logger.info("Embedding server ready")


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": MODEL_NAME,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local",
        }]
    }


@app.post("/v1/embeddings")
async def create_embeddings(request: EmbeddingRequest):
    texts = request.input if isinstance(request.input, list) else [request.input]
    
    model = get_model()
    loop = asyncio.get_event_loop()
    
    def _embed():
        return list(model.embed(texts))
    
    embeddings = await loop.run_in_executor(None, _embed)
    
    data = [
        EmbeddingData(index=i, embedding=emb.tolist())
        for i, emb in enumerate(embeddings)
    ]
    
    total_tokens = sum(len(t.split()) for t in texts)
    
    return EmbeddingResponse(
        data=data,
        model=MODEL_NAME,
        usage={"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18089, log_level="info")
