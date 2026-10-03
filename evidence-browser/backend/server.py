from __future__ import annotations

import argparse
import os
import threading
import webbrowser

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local CSA Evidence Workspace")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project", default="iamps")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--agents-dir")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        parser.error("the evidence workspace may only bind to loopback")
    if args.agents_dir:
        os.environ["CSA_AGENTS_DIR"] = args.agents_dir
    if not args.no_open:
        url = f"http://127.0.0.1:{args.port}/?system={args.project}"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        import uvicorn
    except ImportError:
        from backend.local_server import serve
        serve("127.0.0.1", args.port)
    else:
        uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port, reload=False)


if __name__ == "__main__":
    main()
