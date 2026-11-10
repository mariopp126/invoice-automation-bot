"""Send a sample invoice to the local /process endpoint."""

import argparse
import json
import mimetypes
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Invoice image or PDF")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL")
    parser.add_argument("--api-key", default="", help="Value for X-API-Key, if configured")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    endpoint = args.url.rstrip("/") + "/process"

    with path.open("rb") as file_handle:
        response = httpx.post(
            endpoint,
            files={"file": (path.name, file_handle, mime_type)},
            headers=headers,
            timeout=120.0,
        )

    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(response.text)

    response.raise_for_status()


if __name__ == "__main__":
    main()
