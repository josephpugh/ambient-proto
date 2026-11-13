"""python -m ambient

Settings come from backend/.env (if present) or the shell: OPENAI_API_KEY, OPENAI_BASE_URL, MODEL,
SUMMARY_MODEL, HOST, PORT, PUBLIC_URL, MAX_ITERATIONS. See backend/README or setup.sh for the
virtual environment. Nothing is checked at startup: a missing key simply makes the OpenAI call fail,
and that failure is reported to the UI as an error event on the turn.
"""

import os
import sys
from pathlib import Path


def load_env() -> None:
    """backend/.env, if present, without overriding variables already in the shell."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def main() -> None:
    load_env()
    import uvicorn
    from .a2a_server import create_app

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "9999"))
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix) or bool(os.getenv("VIRTUAL_ENV"))
    print(f"ambient backend on http://{host}:{port}  (python {sys.version.split()[0]}, {'venv' if in_venv else 'system python'})")
    if not os.getenv("OPENAI_API_KEY"):
        print("note: OPENAI_API_KEY is not set, model calls will fail until it is")
    uvicorn.run(create_app(), host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
