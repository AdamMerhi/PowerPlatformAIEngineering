"""Read-only Azure OpenAI connectivity check. Reads credentials from env vars only.

Requires: pip install requests
"""
import os
import sys

import requests


def main():
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    key = os.environ["AZURE_OPENAI_KEY"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "claims-llm")

    resp = requests.post(
        f"{endpoint}/chat/completions",
        headers={"api-key": key, "Content-Type": "application/json"},
        json={
            "model": deployment,
            "messages": [{"role": "user", "content": "Reply with the single word: connected"}],
            "max_completion_tokens": 5,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print("deployment:", deployment)
    print("reply:", data["choices"][0]["message"]["content"].strip())


if __name__ == "__main__":
    try:
        main()
    except KeyError as missing:
        sys.exit(f"missing env var: {missing}")
    except requests.HTTPError as exc:
        sys.exit(f"HTTP error: {exc.response.status_code} {exc.response.text[:200]}")
