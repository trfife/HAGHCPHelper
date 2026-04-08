"""ACP (Agent Client Protocol) client for Copilot CLI.

Implements the JSON-RPC 2.0 / NDJSON-over-TCP protocol to communicate
with `copilot --acp --port <port>`.

Protocol reference: https://agentclientprotocol.com/protocol/overview
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

ACP_PROTOCOL_VERSION = 1
CLIENT_NAME = "ghcp_conversation"
CLIENT_VERSION = "2.0.1"


class ACPError(Exception):
    """ACP protocol or connection error."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


class ACPClient:
    """Async ACP client over NDJSON/TCP."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id = 0
        self._session_id: str | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self, timeout: float = 10.0) -> None:
        """Open a TCP connection to the ACP server."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ACPError(f"Cannot connect to ACP at {self._host}:{self._port}: {err}") from err

    async def async_close(self) -> None:
        """Close the TCP connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            finally:
                self._writer = None
                self._reader = None

    @property
    def connected(self) -> bool:
        """Return True if the connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    # ------------------------------------------------------------------
    # Low-level JSON-RPC helpers
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send(self, msg: dict[str, Any]) -> None:
        """Write a single NDJSON line."""
        if not self._writer:
            raise ACPError("Not connected")
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

    async def _read_line(self, timeout: float = 120.0) -> dict[str, Any]:
        """Read a single NDJSON line with timeout."""
        if not self._reader:
            raise ACPError("Not connected")
        try:
            raw = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        except asyncio.TimeoutError as err:
            raise ACPError("ACP read timeout") from err
        if not raw:
            raise ACPError("ACP connection closed")
        return json.loads(raw)

    async def _send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> int:
        """Send a JSON-RPC request and return the request id."""
        req_id = self._next_id()
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        await self._send(msg)
        return req_id

    async def _send_response(
        self, req_id: int | str | None, result: Any
    ) -> None:
        """Send a JSON-RPC response (Client → Agent)."""
        await self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    async def async_initialize(self) -> dict[str, Any]:
        """Perform the ACP initialize handshake.

        Returns the agent's capabilities dict.
        """
        req_id = await self._send_request(
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {
                    "name": CLIENT_NAME,
                    "title": "GitHub Copilot Conversation for HA",
                    "version": CLIENT_VERSION,
                },
            },
        )
        resp = await self._read_line()
        if resp.get("id") != req_id:
            raise ACPError(f"Unexpected response id: {resp}")
        if "error" in resp:
            err = resp["error"]
            raise ACPError(err.get("message", str(err)), err.get("code", 0))
        return resp.get("result", {})

    async def async_new_session(
        self,
        cwd: str = "/homeassistant",
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a new ACP session.

        Returns the session ID.
        """
        req_id = await self._send_request(
            "session/new",
            {
                "cwd": cwd,
                "mcpServers": mcp_servers or [],
            },
        )
        resp = await self._read_line()
        if resp.get("id") != req_id:
            raise ACPError(f"Unexpected response id: {resp}")
        if "error" in resp:
            err = resp["error"]
            raise ACPError(err.get("message", str(err)), err.get("code", 0))
        self._session_id = resp["result"]["sessionId"]
        return self._session_id

    async def async_prompt(
        self,
        text: str,
        session_id: str | None = None,
        timeout: float = 180.0,
    ) -> str:
        """Send a user prompt and collect the full agent response.

        Handles streaming session/update notifications, auto-approves
        permission requests, and returns the accumulated text response.
        """
        sid = session_id or self._session_id
        if not sid:
            raise ACPError("No session — call async_new_session() first")

        req_id = await self._send_request(
            "session/prompt",
            {
                "sessionId": sid,
                "prompt": [{"type": "text", "text": text}],
            },
        )

        response_text: list[str] = []
        deadline = asyncio.get_event_loop().time() + timeout

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ACPError("ACP prompt timeout")

            msg = await self._read_line(timeout=remaining)

            # --- JSON-RPC response to our prompt request → turn is done ---
            if msg.get("id") == req_id:
                if "error" in msg:
                    err = msg["error"]
                    raise ACPError(
                        err.get("message", str(err)), err.get("code", 0)
                    )
                # Turn complete
                break

            # --- Notification (no "id") ---------------------------------
            if "id" not in msg:
                self._handle_notification(msg, response_text)
                continue

            # --- Agent request to client (has "id" + "method") ----------
            if "method" in msg:
                await self._handle_agent_request(msg)
                continue

        return "".join(response_text).strip()

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_notification(
        self, msg: dict[str, Any], response_text: list[str]
    ) -> None:
        """Process a session/update notification."""
        params = msg.get("params", {})
        update = params.get("update", {})
        update_type = update.get("sessionUpdate")

        if update_type == "agent_message_chunk":
            content = update.get("content", {})
            if content.get("type") == "text":
                response_text.append(content.get("text", ""))
        elif update_type == "agent_thought_chunk":
            # Reasoning; ignore for final output
            pass
        elif update_type in ("tool_call", "tool_call_update"):
            _LOGGER.debug("ACP tool activity: %s", update.get("title", update_type))
        elif update_type == "plan":
            _LOGGER.debug("ACP plan update")
        else:
            _LOGGER.debug("ACP notification: %s", update_type)

    async def _handle_agent_request(self, msg: dict[str, Any]) -> None:
        """Respond to requests the agent sends to the client."""
        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if method == "session/request_permission":
            # Auto-approve: pick the first "allow" option
            options = params.get("options", [])
            option_id = None
            for opt in options:
                if opt.get("kind") in ("allow_once", "allow_always"):
                    option_id = opt["optionId"]
                    break
            if option_id is None and options:
                option_id = options[0]["optionId"]
            await self._send_response(
                req_id,
                {"outcome": "selected", "optionId": option_id},
            )
            return

        if method == "fs/read_text_file":
            # Minimal fs support — read from local filesystem
            path = params.get("path", "")
            try:
                async with asyncio.timeout(5):
                    content = await asyncio.to_thread(self._read_file, path)
                await self._send_response(req_id, {"content": content})
            except Exception as err:
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32002,
                            "message": f"Cannot read file: {err}",
                        },
                    }
                )
            return

        if method == "fs/write_text_file":
            path = params.get("path", "")
            content = params.get("content", "")
            try:
                async with asyncio.timeout(5):
                    await asyncio.to_thread(self._write_file, path, content)
                await self._send_response(req_id, {})
            except Exception as err:
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32002,
                            "message": f"Cannot write file: {err}",
                        },
                    }
                )
            return

        # Unknown method — return method-not-found
        _LOGGER.debug("ACP: unsupported agent request: %s", method)
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not supported: {method}",
                },
            }
        )

    @staticmethod
    def _read_file(path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ------------------------------------------------------------------
    # High-level convenience
    # ------------------------------------------------------------------

    async def async_validate(self, timeout: float = 15.0) -> bool:
        """Check if the ACP server is reachable and responds to initialize."""
        try:
            await self.async_connect(timeout=timeout)
            await self.async_initialize()
            return True
        except ACPError:
            return False
        finally:
            await self.async_close()
