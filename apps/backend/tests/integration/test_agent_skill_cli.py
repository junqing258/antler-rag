import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from uuid import uuid4

SCRIPT = Path(__file__).resolve().parents[4] / "skills/antler-rag/scripts/rag.py"
KB_ID = str(uuid4())
DOC_ID = str(uuid4())


@contextmanager
def api_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append((self.command, self.path, self.headers.get("X-API-Key"), body))
            if self.headers.get("X-API-Key") == "bad":
                status, result = (
                    401,
                    {"code": "invalid_api_key", "message": "Invalid key", "request_id": "req-1"},
                )
            elif self.headers.get("X-API-Key") == "redirect":
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{self.server.server_port}/elsewhere"
                )
                self.end_headers()
                return
            elif body and body.get("knowledge_base_id") != KB_ID:
                status, result = (
                    404,
                    {"code": "not_found", "message": "KB missing", "request_id": "req-2"},
                )
            elif self.path == "/api/v1/agentic-rag" and self.headers.get("X-API-Key") == "limited":
                status, result = (
                    403,
                    {
                        "code": "insufficient_scope",
                        "message": "Scope missing",
                        "request_id": "req-4",
                    },
                )
            elif self.path == "/api/v1/agentic-rag" and self.headers.get("X-API-Key") == "disabled":
                status, result = (
                    503,
                    {"code": "feature_disabled", "message": "Agentic off", "request_id": "req-3"},
                )
            elif self.path == "/api/v1/agentic-rag":
                status, result = (
                    200,
                    {"answer": "Answer", "sources": [{"filename": "source.txt", "chunk_index": 0}]},
                )
            elif self.path == "/api/v1/knowledge-bases":
                status, result = 200, {"items": [{"id": KB_ID, "name": "Test"}]}
            elif self.path == "/api/v1/graph/search":
                status, result = (
                    200,
                    {"results": [{"document_id": DOC_ID, "content": "A relates B"}]},
                )
            else:
                status, result = 200, {"results": [{"filename": "source.txt", "chunk_index": 0}]}
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run_cli(url, key, *args, question=None, query_file=None):
    env = {**os.environ, "ANTLER_RAG_URL": url, "ANTLER_RAG_KEY": key}
    with query_file.open(encoding="utf-8") if query_file else nullcontext(None) as stream:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=question,
            stdin=stream,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )


def test_cli_commands_preserve_query_and_response_shape(tmp_path: Path) -> None:
    side_effect = tmp_path / "should-not-exist"
    query = f"  \"quoted\" 'single' `whoami` $(touch {side_effect})\nANTLER_QUERY\n  "
    query_file = tmp_path / "query.txt"
    query_file.write_text(query, encoding="utf-8")
    with api_server() as (url, seen):
        listed = run_cli(url, "good", "list-kbs")
        retrieved = run_cli(
            url,
            "good",
            "retrieve",
            "--kb",
            KB_ID,
            "--document-ids",
            DOC_ID,
            "--score-threshold",
            "0.5",
            "--rerank",
            query_file=query_file,
        )
        asked = run_cli(url, "good", "ask", "--kb", KB_ID, question=query_file.read_text())
        graphed = run_cli(
            url,
            "good",
            "graph-search",
            "--kb",
            KB_ID,
            "--document-ids",
            DOC_ID,
            question=query_file.read_text(),
        )
    query_file.unlink()
    assert listed.returncode == retrieved.returncode == asked.returncode == graphed.returncode == 0
    assert json.loads(listed.stdout)["items"][0]["id"] == KB_ID
    assert json.loads(retrieved.stdout)["results"][0]["filename"] == "source.txt"
    assert json.loads(asked.stdout)["answer"] == "Answer"
    assert json.loads(graphed.stdout)["results"][0]["document_id"] == DOC_ID
    assert [row[1] for row in seen] == [
        "/api/v1/knowledge-bases",
        "/api/v1/retrieve",
        "/api/v1/agentic-rag",
        "/api/v1/graph/search",
    ]
    assert all(row[2] == "good" for row in seen)
    assert seen[1][3] == {
        "knowledge_base_id": KB_ID,
        "query": query,
        "top_k": 5,
        "document_ids": [DOC_ID],
        "score_threshold": 0.5,
        "rerank": True,
    }
    assert seen[2][3]["message"] == query
    assert seen[3][3]["query"] == query
    assert not side_effect.exists() and not query_file.exists()


def test_cli_errors_are_on_stderr_and_do_not_print_key() -> None:
    with api_server() as (url, _seen):
        cases = [
            (run_cli(url, "bad", "list-kbs"), "[invalid_api_key]", "req-1"),
            (run_cli(url, "redirect", "list-kbs"), "[http_error]", None),
            (
                run_cli(url, "good", "retrieve", "--kb", str(uuid4()), question="test"),
                "[not_found]",
                "req-2",
            ),
            (
                run_cli(url, "disabled", "ask", "--kb", KB_ID, question="test"),
                "[feature_disabled]",
                "req-3",
            ),
            (
                run_cli(url, "limited", "ask", "--kb", KB_ID, question="test"),
                "[insufficient_scope]",
                "req-4",
            ),
            (run_cli(url, "good", "retrieve", "--kb", KB_ID, question=" \n "), "usage:", None),
            (
                run_cli(url, "good", "retrieve", "--kb", "not-a-uuid", question="test"),
                "must be a UUID",
                None,
            ),
            (run_cli("", "good", "list-kbs"), "[configuration_error]", None),
            (run_cli(url, "", "list-kbs"), "[configuration_error]", None),
        ]
    for result, marker, request_id in cases:
        assert result.returncode != 0
        assert result.stdout == ""
        assert marker in result.stderr
        assert "good" not in result.stderr
        if request_id:
            assert request_id in result.stderr


def test_cli_maps_socket_timeout_without_waiting(monkeypatch, capsys) -> None:
    spec = importlib.util.spec_from_file_location("antler_rag_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ANTLER_RAG_URL", "http://localhost:8001")
    monkeypatch.setenv("ANTLER_RAG_KEY", "secret")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "ask", "--kb", KB_ID])
    monkeypatch.setattr(sys, "stdin", io.StringIO("hello"))
    with patch.object(module.urllib.request, "build_opener") as opener:
        opener.return_value.open.side_effect = socket.timeout
        assert module.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "[timeout]" in output.err and "120 seconds" in output.err
