"""ローカル起動: python run_local.py → http://localhost:8080"""

import os
from pathlib import Path


def load_env() -> None:
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


if __name__ == "__main__":
    load_env()
    import uvicorn

    uvicorn.run("app.web.app:app", host="127.0.0.1", port=8080)
