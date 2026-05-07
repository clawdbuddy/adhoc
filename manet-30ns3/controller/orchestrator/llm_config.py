"""LLM / AI 模型配置模块。

从环境变量读取 API 配置，支持 DeepSeek / OpenAI / Anthropic 等提供商。
用法：
    from controller.orchestrator.llm_config import get_llm_client
    client = get_llm_client("deepseek")
    response = client.chat.completions.create(...)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    """单个 LLM 提供商的配置。"""
    name: str
    api_base: str
    api_key: str
    model: str
    timeout: int = 60


class LLMConfigError(Exception):
    """配置缺失或无效时抛出。"""


def _env(key: str, default: Optional[str] = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise LLMConfigError(f"Missing environment variable: {key}")
    return val


def get_deepseek_config() -> LLMConfig:
    """读取 DeepSeek 配置（OpenAI 兼容接口）。"""
    return LLMConfig(
        name="deepseek",
        api_base=_env("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        api_key=_env("DEEPSEEK_API_KEY"),
        model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=int(_env("DEEPSEEK_TIMEOUT", "60")),
    )


def get_anthropic_config() -> LLMConfig:
    """读取 Anthropic / Claude 配置。"""
    return LLMConfig(
        name="anthropic",
        api_base=_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        api_key=_env("ANTHROPIC_API_KEY"),
        model=_env("ANTHROPIC_MODEL", "claude-3-sonnet-20240229"),
        timeout=int(_env("ANTHROPIC_TIMEOUT", "60")),
    )


def get_openai_config() -> LLMConfig:
    """读取 OpenAI 配置。"""
    return LLMConfig(
        name="openai",
        api_base=_env("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key=_env("OPENAI_API_KEY"),
        model=_env("OPENAI_MODEL", "gpt-4"),
        timeout=int(_env("OPENAI_TIMEOUT", "60")),
    )


_PROVIDERS = {
    "deepseek": get_deepseek_config,
    "anthropic": get_anthropic_config,
    "openai": get_openai_config,
}


def get_llm_config(provider: str = "deepseek") -> LLMConfig:
    """按提供商名称获取配置。"""
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise LLMConfigError(f"Unknown provider: {provider}. Supported: {list(_PROVIDERS.keys())}")
    return fn()


def get_llm_client(provider: str = "deepseek"):
    """返回已配置好的 OpenAI 兼容客户端实例。

    需要安装 `openai` 包：pip install openai
    """
    cfg = get_llm_config(provider)
    try:
        import openai
    except ImportError as e:
        raise LLMConfigError("openai package not installed. Run: pip install openai") from e

    return openai.OpenAI(
        base_url=cfg.api_base,
        api_key=cfg.api_key,
        timeout=cfg.timeout,
    )
