"""A scripted OpenAI-compatible provider, for checks that must not cost anything.

Stdlib only, loopback only, no persistence and no upstream: every answer is the same
canned text with the same token counts, so a monthly cap can be hit on a turn you can
predict. The whole point is that "real engine" and "real money" are different things -
the engine believes it is talking to a provider, and nothing is billed.

Run: .venv/Scripts/python.exe tools/mock_openai.py [port]     (default 8999)
Or import it: mock_openai.serve(8999) starts it on a daemon thread.

The text arrives in one read, not one character at a time: this is a scripted provider,
not a latency simulator, and a pass that measures smoothness proves nothing.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = "mock answer, scripted by tools/mock_openai.py"
TOOL_ANSWER = "the tool round trip came back"
#: Fixed, so `used + 1` as a cap is a turn you can plan.
USAGE = {"prompt_tokens": 100, "completion_tokens": 50}
MODELS = ["mini", "small"]
#: A prompt containing this word gets a tool call first, which is how the pass reaches a
#: multi-step turn and sees Router.events() re-yield its skip notes.
TOOL_MARKER = "TOOL"
TOOL_ARGS = '{"text": "echo round trip"}'


def text_chunks(text: str) -> list[dict]:
    chunks = [{"choices": [{"index": 0, "delta": {"content": word + " "}}]} for word in text.split()]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE})
    return chunks


def tool_call_chunks(name: str = "echo", arguments: str = TOOL_ARGS) -> list[dict]:
    #: The tool-call completion carries its usage too, the way a real completion does: a turn
    #: that makes two completions costs two completions. A provider that dropped the field
    #: would quietly under-report the month's spend, and the cap meter would read low.
    half = len(arguments) // 2
    return [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "id": "call_lab_1", "type": "function", "function": {"name": name, "arguments": ""}}]},
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[:half]}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[half:]}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}], "usage": USAGE},
    ]


#: Prompt word → the one tool that word asks for. Stage six of the browser pass needs a
#: different tool per prompt, and a scripted provider is the only thing that can promise it.
TOOL_ROUTES = (
    ("write_file", "write_file", '{"path": "made.txt", "content": "made by the lab\\n"}'),
    ("demo_lookup", "demo_lookup", '{"id": "42"}'),
    ("unittest", "run_command", '{"argv": ["python", "-m", "unittest", "discover"]}'),
    ("failing", "run_command", '{"argv": ["python", "-c", "import sys; sys.exit(3)"]}'),
    ("findskill", "search_skills", '{"query": "tdd"}'),
    ("loadskill", "use_skill", '{"name": "agent-eval"}'),
)


def reply_for(payload: dict) -> list[dict]:
    """A turn that already carries a tool result is the loop's second step: answer it."""
    messages = payload.get("messages") or []
    if any(m.get("role") == "tool" for m in messages):
        return text_chunks(TOOL_ANSWER)
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    content = str(last_user.get("content") or "")
    for marker, name, arguments in TOOL_ROUTES:
        if marker in content:
            return tool_call_chunks(name, arguments)
    if TOOL_MARKER in content:
        return tool_call_chunks()
    return text_chunks(ANSWER)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # a pass reads the UI, not access logs
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/demo/"):
            record = {"id": self.path.rsplit("/", 1)[-1].split("?")[0], "name": "widget"}
            self._send(200, json.dumps(record).encode(), "application/json")
            return
        if self.path.rstrip("/").endswith("/models"):
            data = {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}
            self._send(200, json.dumps(data).encode(), "application/json")
            return
        self._send(404, b'{"error":{"message":"mock serves /v1/models and /demo/{id}"}}', "application/json")

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, b'{"error":{"message":"mock serves /v1/chat/completions only"}}', "application/json")
            return
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":{"message":"mock needs a JSON body"}}', "application/json")
            return
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in reply_for(payload)) + "data: [DONE]\n\n"
        self._send(200, body.encode(), "text/event-stream")


def serve(port: int = 8999) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # loopback only, like the engine
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    wanted = int(sys.argv[1]) if len(sys.argv) > 1 else 8999
    print(f"[mock] http://127.0.0.1:{wanted}/v1  models={MODELS} usage={USAGE} marker={TOOL_MARKER!r}", file=sys.stderr)
    serve(wanted).serve_forever()
