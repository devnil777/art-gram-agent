"""
llm_client.py - LiteLLM wrapper for calling language models.

Provides a single function to call the LLM with system and user prompts.
Configured to work with Ollama backend by default.
"""

import json
import logging
import re
import time
from typing import List

import litellm

from processor_config_loader import LLMModelConfig

litellm.suppress_debug_info = True

log = logging.getLogger("tg_collector")


def call_llm(models: List[LLMModelConfig], system_prompt: str, user_content: str) -> str:
    """
    Send a request to the LLM and return the raw response text.
    Loops through available models and retries on errors.

    Args:
        models: List of LLMModelConfig.
        system_prompt: System instruction (prompt template).
        user_content: User message content (the text to process).

    Returns:
        Raw text response from the LLM, potentially prepended with a marker.

    Raises:
        Exception: On network errors, timeouts, or empty responses if all models fail.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    last_error = None
    delays = [2, 4, 8]

    for model_config in models:
        if not model_config.enabled:
            continue
            
        model_name = model_config.model
        log.debug("Calling LLM model=%s, api_base=%s", model_name, model_config.api_base)

        params = {
            "model": model_name,
            "messages": messages
        }

        if model_config.api_key:
            params["api_key"] = model_config.api_key
        if model_config.api_base:
            params["api_base"] = model_config.api_base

        if model_config.temperature > 0:
            params["temperature"] = model_config.temperature

        if model_config.max_tokens > 0:
            params["max_tokens"] = model_config.max_tokens

        if model_config.timeout > 0:
            params["timeout"] = model_config.timeout

        for attempt in range(len(delays) + 1):
            try:
                response = litellm.completion(**params)
                
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("LLM returned empty response")
                
                content = content.strip()
                log.debug("LLM response length: %d chars", len(content))
                
                # Prepend the marker
                if model_config.marker:
                    content = f"{model_config.marker} {content}"
                    
                return content

            except Exception as e:
                error_str = str(e)
                parsed = False
                
                json_match = re.search(r'(\{.*\})', error_str, re.DOTALL)
                if json_match:
                    try:
                        err_data = json.loads(json_match.group(1))
                        if "error" in err_data:
                            code = err_data["error"].get("code", "unknown")
                            status = err_data["error"].get("status", "unknown")
                            msg = err_data["error"].get("message", "unknown")
                            log.warning(
                                "Model %s error (attempt %d): code=%s, status=%s, message=%s",
                                model_name, attempt + 1, code, status, msg
                            )
                            parsed = True
                    except Exception:
                        pass
                
                if not parsed:
                    short_err = error_str.split('\n')[0][:200]
                    log.warning("Model %s error (attempt %d): %s - %s", model_name, attempt + 1, e.__class__.__name__, short_err)
                
                last_error = e
                
                if attempt < len(delays):
                    delay = delays[attempt]
                    log.info("Waiting %d seconds before retry...", delay)
                    time.sleep(delay)
                else:
                    log.warning("Exhausted retries for model %s, moving to next model.", model_name)
    
    raise Exception(f"All models failed. Last error: {str(last_error)}")
