"""YandexGPT (Yandex Cloud Foundation Models) client.

Implements the same ``discover(system_instruction, user_content,
temperature)`` contract as the phase Gemini clients, so it plugs straight
into the discovery loops and the key-rotation wrapper.

Auth notes (as of 2026):
- Endpoint:  POST https://llm.api.cloud.yandex.net/foundationModels/v1/completion
- Headers:   ``Authorization: Api-Key <API_KEY>`` + ``x-folder-id: <FOLDER_ID>``
  (the folder id is required when authenticating with an API key).
- Body:      ``modelUri`` = ``gpt://<folder_id>/<model>``,
  ``messages`` with ``role`` + ``text``, ``completionOptions``.
- Response:  ``result.alternatives[0].message.text``.

The API keys you supplied for this project start with ``AQ.`` — that is the
Yandex Cloud API-key format (Gemini keys start with ``AIza``). Add the
folder id of the Yandex Cloud folder the key belongs to in Settings, and
these keys become usable for live runs.
"""
from __future__ import annotations

import json
from typing import Any

import requests

ENDPOINT = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
DEFAULT_MODEL = "yandexgpt/latest"  # stable alias; or "yandexgpt-lite/latest"


class YandexGPTClient:
    """Thin wrapper over the Yandex Cloud completion API."""

    def __init__(self, api_key: str, folder_id: str = "", model: str = DEFAULT_MODEL):
        if not api_key:
            raise ValueError("Yandex API key is empty.")
        if not folder_id:
            raise ValueError(
                "Yandex keys need the Cloud **folder id** (x-folder-id header). "
                "Find it in Yandex Cloud console (folder ID) and add it in Settings → API keys."
            )
        # The shared settings hold a Gemini model name by default; Yandex
        # modelUri needs a Yandex model (e.g. "yandexgpt/latest"). Fall back
        # to the stable default when the configured model is not a Yandex one.
        if not model or "/" not in model or "gemini" in model.lower():
            model = DEFAULT_MODEL
        self._api_key = api_key
        self._folder_id = folder_id
        self._model = model
        self._session = requests.Session()
        self.last_model: str | None = model  # which model served the last call

    @property
    def model(self) -> str:
        return self._model

    def discover(self, system_instruction: str, user_content: str, temperature: float = 0.2) -> str:
        payload: dict[str, Any] = {
            "modelUri": f"gpt://{self._folder_id}/{self._model}",
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": "2000",
            },
            "messages": [
                {"role": "system", "text": system_instruction},
                {"role": "user", "text": user_content},
            ],
        }
        response = self._session.post(
            ENDPOINT,
            headers={
                "Authorization": f"Api-Key {self._api_key}",
                "x-folder-id": self._folder_id,
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=120,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"YandexGPT API {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        try:
            return body["result"]["alternatives"][0]["message"]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected YandexGPT response: {str(body)[:300]}") from exc
