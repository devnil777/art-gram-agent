"""
llm_client.py - LiteLLM wrapper for calling language models.

Provides a single function to call the LLM with system and user prompts.
Configured to work with Ollama backend by default.
"""

import logging

import litellm

from processor_config_loader import LLMConfig

litellm.suppress_debug_info = True

log = logging.getLogger("tg_collector")


def call_llm(config: LLMConfig, system_prompt: str, user_content: str) -> str:
    """
    Send a request to the LLM and return the raw response text.

    Args:
        config: LLM configuration with model, api_base, etc.
        system_prompt: System instruction (prompt template).
        user_content: User message content (the text to process).

    Returns:
        Raw text response from the LLM.

    Raises:
        Exception: On network errors, timeouts, or empty responses.
    """
    # Model name is used as-is from config.
    # For Ollama, the user should set e.g. "ollama/gpt-oss:20b" in config.
    model_name = config.model

    log.debug("Calling LLM model=%s, api_base=%s", model_name, config.api_base)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    params = {
        "model": model_name,
        "messages": messages
#,        "extra_body": {"thinking": {"type": "disabled"}}
    }

    # Добавляем api_key, если он задан
    if config.api_key:
        params["api_key"] = config.api_key
    if config.api_base:
        params["api_base"] = config.api_base

    # Добавляем числовые параметры только если они > 0
    if config.temperature > 0:
        params["temperature"] = config.temperature

    if config.max_tokens > 0:
        params["max_tokens"] = config.max_tokens

    if config.timeout > 0:
        params["timeout"] = config.timeout

    response = litellm.completion(**params)

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("LLM returned empty response")

    log.debug("LLM response length: %d chars", len(content))
    return content.strip()
