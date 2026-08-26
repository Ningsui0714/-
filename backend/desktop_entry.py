"""Packaged FastAPI sidecar entry point for the Tauri desktop application."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import runpy
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="LearnFlow desktop API sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--run-python-script", metavar="PATH")
    args = parser.parse_args()

    if args.run_python_script:
        script_path = os.path.abspath(args.run_python_script)
        if not os.path.isfile(script_path):
            parser.error("script path does not exist")
        sys.argv = [script_path]
        runpy.run_path(script_path, run_name="__main__")
        return

    if args.port is None:
        parser.error("--port is required")
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("desktop sidecar may only bind a loopback address")
    if os.getenv("DESKTOP_MODE", "").lower() != "true":
        parser.error("DESKTOP_MODE=true is required")
    if not os.getenv("DESKTOP_TOKEN"):
        parser.error("DESKTOP_TOKEN is required")
    from app.main import app
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=os.getenv("LEARNFLOW_LOG_LEVEL", "info"),
        access_log=False,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
