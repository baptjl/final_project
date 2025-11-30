"""Quick helper to test connectivity to the Ollama endpoint configured for this project.

Usage:
    /path/to/.venv/bin/python -m automodel.src.llm.check_ollama

It will attempt a tiny prompt and print the response or a friendly error.
"""
from __future__ import annotations
import sys
from automodel.src.llm.ollama_client import _call_ollama, OLLAMA_URL, OLLAMA_MODEL

TEST_PROMPT = "Return the single word: pong"


def main():
    print(f"Testing Ollama at: {OLLAMA_URL} (model={OLLAMA_MODEL})")
    try:
        resp = _call_ollama(TEST_PROMPT, max_retries=1)
        if not resp:
            print("No response received from Ollama.")
            sys.exit(2)
        print("Ollama response:\n", resp)
    except Exception as e:
        print("Failed to contact Ollama:", type(e).__name__, str(e))
        print("If you don't have Ollama installed, see https://ollama.com/docs for install and model pull instructions.")
        sys.exit(1)


if __name__ == '__main__':
    main()
