import os
from dataclasses import dataclass

from openai import OpenAI


AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
AGNES_MODEL_NAME = "agnes-2.0-flash"
PLACEHOLDER_VALUES = {
    "",
    "your_api_key_here",
    "your_apikey_here",
    "your_agnes_api_key_here",
    "默认使用通义千问,apikey通过百炼模型平台获取",
}


@dataclass(frozen=True)
class ModelProviderConfig:
    provider: str
    api_key: str
    base_url: str
    model_name: str


def _clean(value: str) -> str:
    return (value or "").strip()


def _is_real_secret(value: str) -> bool:
    return _clean(value) not in PLACEHOLDER_VALUES


def has_model_api_key() -> bool:
    return _is_real_secret(os.getenv("AGNES_API_KEY")) or _is_real_secret(os.getenv("API_KEY"))


def resolve_model_config() -> ModelProviderConfig:
    provider = _clean(os.getenv("MODEL_PROVIDER", "agnes")).lower()

    if provider == "agnes":
        api_key = _clean(os.getenv("AGNES_API_KEY") or os.getenv("API_KEY"))
        base_url = _clean(os.getenv("AGNES_BASE_URL") or os.getenv("MODEL_BASE_URL") or AGNES_BASE_URL)
        model_name = _clean(os.getenv("AGNES_MODEL_NAME") or os.getenv("MODEL_NAME") or AGNES_MODEL_NAME)
    else:
        api_key = _clean(os.getenv("API_KEY") or os.getenv("AGNES_API_KEY"))
        base_url = _clean(os.getenv("MODEL_BASE_URL") or os.getenv("AGNES_BASE_URL") or AGNES_BASE_URL)
        model_name = _clean(os.getenv("MODEL_NAME") or os.getenv("AGNES_MODEL_NAME") or AGNES_MODEL_NAME)

    return ModelProviderConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )


def get_model_name() -> str:
    return resolve_model_config().model_name


def create_model_client() -> OpenAI:
    config = resolve_model_config()
    return OpenAI(api_key=config.api_key, base_url=config.base_url)
