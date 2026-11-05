"""Local model interface with explicit configuration."""
import json
from typing import Any, Protocol
from urllib import error, request

class LLMClientError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str
    provider: str

    def structured_response(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        pass

    def text_response(
        self,
        *,
        instructions: str,
        input_text: str,
    ) -> str:
        pass


class OllamaLLMClient:
    """Small local-chat LLM client for local background work."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300,
    ):
        self.provider = "ollama"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def structured_response(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        content = self._chat(
            instructions=(
                f"{instructions}\n\nReturn only JSON for schema `{schema_name}`. "
                "Do not wrap it in markdown."
            ),
            input_text=f"{input_text}\n\nJSON schema:\n{json.dumps(schema)}",
            json_mode=True,
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError("Ollama returned non-JSON output.") from exc

    def text_response(
        self,
        *,
        instructions: str,
        input_text: str,
    ) -> str:
        return self._chat(instructions=instructions, input_text=input_text, json_mode=False)

    def _chat(self, *, instructions: str, input_text: str, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
        }
        if json_mode:
            payload["format"] = "json"
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, json.JSONDecodeError, error.URLError) as exc:
            raise LLMClientError(f"Ollama chat call failed for model {self.model}.") from exc
        content = raw.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("Ollama returned an empty response.")
        return content.strip()
