from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a deterministic Learning Agent UI screenshot.")
    parser.add_argument("--code-root", default=str(Path(__file__).resolve().parents[1]), help="Codebase to import for the demo server.")
    parser.add_argument("--out", required=True, help="Output PNG path.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4010)
    parser.add_argument("--path", default="/?question_id=core_prefill")
    parser.add_argument("--window-size", default="1600,1100")
    parser.add_argument("--chrome-path", default=str(DEFAULT_CHROME))
    return parser


def wait_for_http(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - best effort polling
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> None:
    args = build_parser().parse_args()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    code_root = Path(args.code_root).resolve()
    demo_script = Path(__file__).resolve().with_name("demo_ui_server.py")
    url = f"http://{args.host}:{args.port}{args.path}"
    server = subprocess.Popen(
        [
            sys.executable,
            str(demo_script),
            "--code-root",
            str(code_root),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_http(url)
        chrome = Path(args.chrome_path)
        if not chrome.exists():
            raise FileNotFoundError(f"Chrome binary not found at {chrome}")
        subprocess.run(
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={args.window_size}",
                f"--screenshot={out_path}",
                url,
            ],
            check=True,
        )
        print(f"Saved screenshot to {out_path}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
