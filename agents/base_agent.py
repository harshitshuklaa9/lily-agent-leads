import json
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class BaseAgent:
    model_key: str = ""  # subclasses set this to their key in config["models"]

    def __init__(self, config: dict):
        self.config = config
        # Per-agent model override > root model > default
        self.model = (
            config.get("models", {}).get(self.model_key)
            or config.get("model", "gpt-4o")
        )
        self.max_retries = config.get("retry", {}).get("max_retries", 1)
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.logger = logging.getLogger(self.__class__.__name__)

    def call_llm(self, system_prompt: str, user_prompt: str, expect_json: bool = True) -> Any:
        """
        Call the OpenAI API. If expect_json=True, parses and returns a dict/list.
        Retries on malformed JSON and 429 rate limit errors with exponential backoff.
        """
        attempts = 0
        last_error = None
        rate_limit_backoff = 5  # seconds, doubles on each 429

        while attempts <= self.max_retries:
            try:
                kwargs = dict(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                if expect_json:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

                if expect_json:
                    return json.loads(content)
                return content

            except RateLimitError as e:
                last_error = e
                self.logger.warning(
                    "Rate limit hit (attempt %d) — sleeping %ds before retry",
                    attempts + 1, rate_limit_backoff
                )
                time.sleep(rate_limit_backoff)
                rate_limit_backoff = min(rate_limit_backoff * 2, 60)  # cap at 60s
                attempts += 1
            except json.JSONDecodeError as e:
                last_error = e
                self.logger.warning("JSON parse failed (attempt %d): %s", attempts + 1, e)
                attempts += 1
            except Exception as e:
                self.logger.error("LLM call failed: %s", e)
                raise

        self.logger.error("All retries exhausted. Last error: %s", last_error)
        raise ValueError(f"Could not parse LLM response after {self.max_retries + 1} attempts: {last_error}")

    def validate_output(self, output: Any, required_keys: list[str]) -> bool:
        """
        Validates that a dict output contains all required keys with non-null values.
        Logs a warning for each missing or null field.
        """
        if not isinstance(output, dict):
            self.logger.warning("Output is not a dict: %s", type(output))
            return False

        valid = True
        for key in required_keys:
            if key not in output or output[key] is None:
                self.logger.warning("Missing or null field: '%s'", key)
                output[key] = None
                valid = False

        return valid
