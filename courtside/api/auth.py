"""A single-user password gate for when the desk is reachable from the internet.

This app holds Kalshi keys and can place orders, so anything hosted must be
locked. The rules:

* APP_PASSWORD set     -> every /api call and the WebSocket need a session cookie,
                          obtained by POSTing the password to /api/auth/login.
* hosted, no password  -> locked: nothing but /api/auth/status answers, and it
                          says to set APP_PASSWORD. (Render sets RENDER=true.)
* local, no password   -> open, as on a laptop.

The session is stateless: the cookie is an HMAC of a fixed label keyed by the
password, so it survives restarts and dies when the password changes.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

from fastapi import HTTPException, Request, Response, WebSocket

COOKIE = "courtside_session"
MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = ("/api/auth/", "/health")


class Auth:
    def __init__(self, password: str, hosted: bool):
        self.password = password.strip()
        self.hosted = hosted
        self._failures: list[float] = []

    @property
    def required(self) -> bool:
        return bool(self.password)

    @property
    def locked(self) -> bool:
        """Hosted with no password configured: refuse to serve the desk at all."""
        return self.hosted and not self.password

    def _token(self) -> str:
        return hmac.new(self.password.encode(), b"courtside-session-v1", hashlib.sha256).hexdigest()

    def valid(self, cookie: Optional[str]) -> bool:
        if self.locked:
            return False
        if not self.required:
            return True
        return bool(cookie) and hmac.compare_digest(cookie, self._token())

    def status(self, cookie: Optional[str]) -> dict[str, bool]:
        return {"required": self.required, "locked": self.locked, "authed": self.valid(cookie)}

    def login(self, password: str, response: Response) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < 300]
        if len(self._failures) >= 8:
            raise HTTPException(429, "Too many wrong passwords. Wait a few minutes.")
        if not self.required or not hmac.compare_digest(password.encode(), self.password.encode()):
            self._failures.append(now)
            raise HTTPException(401, "Wrong password.")
        response.set_cookie(
            COOKIE, self._token(), max_age=MAX_AGE, httponly=True, samesite="lax", secure=self.hosted, path="/"
        )

    def check_request(self, request: Request) -> Optional[Response]:
        """Middleware hook: a response to short-circuit with, or None to continue."""
        from fastapi.responses import JSONResponse

        path = request.url.path
        if not path.startswith("/api/") or path.startswith(OPEN_PATHS):
            return None
        if self.locked:
            return JSONResponse({"detail": "Locked: set APP_PASSWORD in the host's environment, then redeploy."}, status_code=503)
        if not self.valid(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        return None

    def check_socket(self, socket: WebSocket) -> bool:
        return self.valid(socket.cookies.get(COOKIE))
