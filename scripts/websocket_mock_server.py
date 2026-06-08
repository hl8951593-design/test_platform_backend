import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="DevTest WebSocket Mock Server", version="1.0.0")


def _first_subprotocol(websocket: WebSocket) -> str | None:
    offered = websocket.headers.get("sec-websocket-protocol", "")
    return offered.split(",", 1)[0].strip() or None


def _message_payload(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("text") is not None:
        text = message["text"]
        try:
            return {"type": "text", "data": text, "json": json.loads(text)}
        except json.JSONDecodeError:
            return {"type": "text", "data": text, "json": None}
    data = message.get("bytes") or b""
    return {"type": "binary", "data": data.hex(), "json": None}


@app.get("/")
async def root():
    return {
        "service": "DevTest WebSocket Mock Server",
        "websocket_endpoints": [
            "/ws/echo",
            "/ws/session/{user_id}",
            "/ws/sequence/{count}",
            "/ws/auth",
            "/ws/close/{code}",
        ],
    }


@app.websocket("/")
@app.websocket("/ws/echo")
async def echo(websocket: WebSocket):
    await websocket.accept(subprotocol=_first_subprotocol(websocket))
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") is not None:
                await websocket.send_text(message["text"])
            else:
                await websocket.send_bytes(message.get("bytes") or b"")
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/session/{user_id}")
async def session(websocket: WebSocket, user_id: int):
    await websocket.accept(subprotocol="json" if "json" in websocket.headers.get("sec-websocket-protocol", "") else None)
    message = await websocket.receive()
    payload = _message_payload(message)
    await websocket.send_json(
        {
            "event": "welcome",
            "user_id": user_id,
            "authorization": websocket.headers.get("authorization"),
            "received": payload,
        }
    )
    await websocket.send_text("done")
    await websocket.close(code=1000)


@app.websocket("/ws/sequence/{count}")
async def sequence(websocket: WebSocket, count: int):
    await websocket.accept()
    for index in range(max(0, min(count, 100))):
        await websocket.send_json({"event": "sequence", "index": index, "total": count})
    await websocket.close(code=1000)


@app.websocket("/ws/auth")
async def auth(websocket: WebSocket):
    if websocket.headers.get("authorization") != "Bearer mock-token":
        await websocket.close(code=1008, reason="invalid authorization")
        return
    await websocket.accept()
    await websocket.send_json({"authenticated": True})
    await websocket.close(code=1000)


@app.websocket("/ws/close/{code}")
async def close(websocket: WebSocket, code: int):
    await websocket.accept()
    await websocket.close(code=code, reason="mock close")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the DevTest WebSocket mock server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
