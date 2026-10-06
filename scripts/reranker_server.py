#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class CrossEncoderRuntime:
    def __init__(
        self,
        model_name: str,
        *,
        max_pairs: int,
        max_pair_chars: int,
    ) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.max_pairs = max_pairs
        self.max_pair_chars = max_pair_chars
        self._lock = threading.Lock()
        self._model = CrossEncoder(model_name)

        # Warm the lazy torch/Metal execution path with the production batch shape
        # before opening the listening socket. A one-pair warmup leaves the first
        # real top-3 request paying compilation/shape setup cost on Apple Silicon.
        warm_query = "тестовый запрос для прогрева reranker"
        warm_passage = ("тестовый документ для прогрева модели " * 40)[:1000]
        warm_pairs = tuple(
            (warm_query, warm_passage)
            for _ in range(min(3, self.max_pairs))
        )
        for _ in range(3):
            self.score_pairs(warm_pairs)

    def score_pairs(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        if len(pairs) > self.max_pairs:
            raise ValueError(f"at most {self.max_pairs} pairs are allowed")
        for query, passage in pairs:
            if len(query) + len(passage) > self.max_pair_chars:
                raise ValueError(
                    f"query + passage must not exceed {self.max_pair_chars} characters"
                )
        if not pairs:
            return ()
        with self._lock:
            raw = self._model.predict(list(pairs))
        return tuple(float(value) for value in raw)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_handler(runtime: CrossEncoderRuntime, *, max_request_bytes: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ArvectumReranker/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, payload: Any) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(404, {"error": "not_found"})
                return
            self._send(
                200,
                {
                    "status": "ok",
                    "provider": "sentence-transformers-cross-encoder",
                    "model": runtime.model_name,
                },
            )

        def do_POST(self) -> None:
            if self.path != "/score":
                self._send(404, {"error": "not_found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return
            if content_length < 1 or content_length > max_request_bytes:
                self._send(413, {"error": "request_too_large"})
                return

            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                requested_model = str(payload.get("model") or "")
                if requested_model != runtime.model_name:
                    raise ValueError("requested model does not match loaded model")
                raw_pairs = payload.get("pairs")
                if not isinstance(raw_pairs, list):
                    raise ValueError("pairs must be a list")
                pairs: list[tuple[str, str]] = []
                for item in raw_pairs:
                    if (
                        not isinstance(item, list)
                        or len(item) != 2
                        or not all(isinstance(value, str) for value in item)
                    ):
                        raise ValueError("each pair must contain query and passage strings")
                    pairs.append((item[0], item[1]))
                scores = runtime.score_pairs(tuple(pairs))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send(400, {"error": "invalid_request", "detail": str(exc)})
                return
            except Exception:
                self._send(503, {"error": "scoring_unavailable"})
                return

            self._send(
                200,
                {
                    "model": runtime.model_name,
                    "scores": list(scores),
                },
            )

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local localhost-only cross-encoder scoring sidecar."
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--max-pairs", type=int, default=20)
    parser.add_argument("--max-pair-chars", type=int, default=12000)
    parser.add_argument("--max-request-bytes", type=int, default=512_000)
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("reranker sidecar must bind to loopback")
    if not 1 <= args.max_pairs <= 100:
        raise SystemExit("--max-pairs must be between 1 and 100")
    if args.max_pair_chars < 256:
        raise SystemExit("--max-pair-chars must be at least 256")

    runtime = CrossEncoderRuntime(
        args.model,
        max_pairs=args.max_pairs,
        max_pair_chars=args.max_pair_chars,
    )
    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(runtime, max_request_bytes=args.max_request_bytes),
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
