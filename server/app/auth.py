import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 5
SCRYPT_KEY_LENGTH = 32
MINIMUM_SALT_LENGTH = 16


def hash_password(password: str, salt: bytes) -> str:
    if len(salt) < MINIMUM_SALT_LENGTH:
        raise ValueError(f"Password salt must be at least {MINIMUM_SALT_LENGTH} bytes")

    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LENGTH,
    )
    return ":".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _encode(salt),
            _encode(derived),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    parsed = _parse_password_hash(encoded_hash)
    if parsed is None:
        return False

    n, r, p, salt, expected = parsed
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def password_hash_is_valid(encoded_hash: str) -> bool:
    return _parse_password_hash(encoded_hash) is not None


class SessionStore:
    def __init__(self, ttl_seconds: int, max_sessions: int = 64) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, int] = {}
        self._lock = threading.Lock()

    def create(self, now: int | None = None) -> str:
        current_time = int(time.time()) if now is None else now
        token = secrets.token_urlsafe(32)
        token_key = _token_key(token)

        with self._lock:
            self._prune(current_time)
            if len(self._sessions) >= self._max_sessions:
                oldest_key = min(self._sessions, key=self._sessions.__getitem__)
                del self._sessions[oldest_key]
            self._sessions[token_key] = current_time + self._ttl_seconds

        return token

    def verify(self, token: str | None, now: int | None = None) -> bool:
        if token is None:
            return False

        current_time = int(time.time()) if now is None else now
        token_key = _token_key(token)
        with self._lock:
            self._prune(current_time)
            expires_at = self._sessions.get(token_key)
            return expires_at is not None and expires_at > current_time

    def revoke(self, token: str | None) -> None:
        if token is None:
            return
        with self._lock:
            self._sessions.pop(_token_key(token), None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _prune(self, current_time: int) -> None:
        expired_keys = [key for key, expires_at in self._sessions.items() if expires_at <= current_time]
        for key in expired_keys:
            del self._sessions[key]


class LoginAttemptLimiter:
    def __init__(self, per_client_limit: int, global_limit: int, window_seconds: int) -> None:
        self._per_client_limit = per_client_limit
        self._global_limit = global_limit
        self._window_seconds = window_seconds
        self._client_attempts: dict[str, deque[float]] = {}
        self._global_attempts: deque[float] = deque()
        self._client_in_flight: dict[str, int] = {}
        self._global_in_flight = 0
        self._lock = threading.Lock()

    def reserve(self, client_key: str, now: float | None = None) -> bool:
        """Atomically reserve capacity before starting password verification."""
        current_time = time.monotonic() if now is None else now
        cutoff = current_time - self._window_seconds

        with self._lock:
            self._prune(cutoff)
            attempts = self._client_attempts.get(client_key)
            client_attempt_count = (len(attempts) if attempts is not None else 0) + self._client_in_flight.get(
                client_key,
                0,
            )
            global_attempt_count = len(self._global_attempts) + self._global_in_flight
            if client_attempt_count >= self._per_client_limit or global_attempt_count >= self._global_limit:
                return False

            self._client_in_flight[client_key] = self._client_in_flight.get(client_key, 0) + 1
            self._global_in_flight += 1
            return True

    def record_failure(self, client_key: str, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        cutoff = current_time - self._window_seconds

        with self._lock:
            self._prune(cutoff)
            self._release_reservation(client_key)
            attempts = self._client_attempts.setdefault(client_key, deque())
            attempts.append(current_time)
            self._global_attempts.append(current_time)

    def record_success(self, client_key: str) -> None:
        with self._lock:
            self._release_reservation(client_key)
            self._client_attempts.pop(client_key, None)

    def cancel(self, client_key: str) -> None:
        """Release a reservation that could not be classified as success or failure."""
        with self._lock:
            self._release_reservation(client_key)

    def clear(self) -> None:
        with self._lock:
            self._client_attempts.clear()
            self._global_attempts.clear()
            self._client_in_flight.clear()
            self._global_in_flight = 0

    def _release_reservation(self, client_key: str) -> None:
        in_flight = self._client_in_flight.get(client_key, 0)
        if in_flight <= 0:
            raise RuntimeError("Login attempt was not reserved")
        if in_flight == 1:
            del self._client_in_flight[client_key]
        else:
            self._client_in_flight[client_key] = in_flight - 1
        self._global_in_flight -= 1

    def _prune(self, cutoff: float) -> None:
        _prune_attempts(self._global_attempts, cutoff)
        expired_clients = []
        for client_key, attempts in self._client_attempts.items():
            _prune_attempts(attempts, cutoff)
            if not attempts:
                expired_clients.append(client_key)
        for client_key in expired_clients:
            del self._client_attempts[client_key]


def _parse_password_hash(encoded_hash: str) -> tuple[int, int, int, bytes, bytes] | None:
    try:
        algorithm, n_text, r_text, p_text, salt_text, expected_text = encoded_hash.split(":", 5)
        n, r, p = int(n_text), int(r_text), int(p_text)
        salt = _decode(salt_text)
        expected = _decode(expected_text)
    except (ValueError, TypeError):
        return None

    supported_parameters = n == SCRYPT_N and r == SCRYPT_R and p == SCRYPT_P
    if algorithm != "scrypt" or not supported_parameters:
        return None
    if len(salt) < MINIMUM_SALT_LENGTH or len(expected) != SCRYPT_KEY_LENGTH:
        return None
    return n, r, p, salt, expected


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_attempts(attempts: deque[float], cutoff: float) -> None:
    while attempts and attempts[0] <= cutoff:
        attempts.popleft()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
