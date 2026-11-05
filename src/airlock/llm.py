"""A loopback-only Ollama adapter; no proxy, redirect, cloud model, or provider fallback."""
import http.client
import json
import math
from urllib.parse import urlsplit
from airlock_core.llm import LLMClientError, OllamaLLMClient


class LocalOllama(OllamaLLMClient):
    def __init__(self, settings):
        super().__init__(model=settings.model, base_url=settings.ollama_url,
                         timeout_seconds=settings.model_timeout)
        self.embedding_model = settings.embedding_model

    def _request(self, path, payload=None):
        url = urlsplit(self.base_url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=self.timeout_seconds)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            conn.request("POST" if body else "GET", path, body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            data = response.read(8_000_001)
            if response.status != 200 or len(data) > 8_000_000:
                raise LLMClientError("Local Ollama request failed. Check the model and local service.")
            return json.loads(data)
        except (OSError, TimeoutError, ValueError, http.client.HTTPException) as exc:
            raise LLMClientError("Local Ollama is unavailable or returned an invalid response. No cloud fallback was used.") from exc
        finally:
            conn.close()

    def text_response(self, *, instructions, input_text):
        # Keep inherited public entry points on the same no-proxy local transport.
        raw = self._request("/api/chat", {
            "model": self.model, "stream": False, "think": False,
            "messages": [{"role": "system", "content": instructions},
                         {"role": "user", "content": input_text}],
        })
        content = raw.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("The local model returned no text.")
        return content

    def check_models(self):
        available = {m["name"]: m for m in self._request("/api/tags").get("models", [])}
        result = {}
        for name in (self.model, self.embedding_model):
            record = available.get(name)
            if not record:
                raise LLMClientError(f"Local model {name} is not installed. Install it explicitly with Ollama.")
            info = self._request("/api/show", {"model": name})
            if record.get("remote_model") or record.get("remote_host") or info.get("remote_model") or info.get("remote_host"):
                raise LLMClientError("Remote Ollama models are disabled in Airlock.")
            result[name] = record.get("digest")
        return result

    def installed_chat_models(self):
        from .config import Settings
        result = []
        for record in self._request('/api/tags').get('models', []):
            name = record.get('name', '')
            try:
                Settings.local_model_name(name)
            except ValueError:
                continue
            if record.get('remote_model') or record.get('remote_host'):
                continue
            info = self._request('/api/show', {'model': name})
            if info.get('remote_model') or info.get('remote_host') or 'completion' not in info.get('capabilities', []):
                continue
            result.append({'name': name, 'size': record.get('size'), 'digest': record.get('digest')})
        return sorted(result, key=lambda r: r['name'])

    def structured_response(self, *, instructions, input_text, schema_name, schema):
        raw = self._request("/api/chat", {
            "model": self.model, "stream": False, "think": False, "format": schema,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": input_text}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 900},
            "keep_alive": "5m",
        })
        try:
            return json.loads(raw["message"]["content"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMClientError("The local model did not return a valid structured response. No change was applied.") from exc

    def embed(self, text):
        raw = self._request("/api/embed", {"model": self.embedding_model, "input": text, "truncate": False})
        vectors = raw.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1 or not isinstance(vectors[0], list):
            raise LLMClientError("Local embedding response was invalid.")
        vector = vectors[0]
        if not 1 <= len(vector) <= 4096 or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise LLMClientError("Local embedding dimensions or values were invalid.")
        return vector
