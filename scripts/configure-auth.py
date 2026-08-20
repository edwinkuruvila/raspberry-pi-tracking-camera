#!/usr/bin/env python3

import getpass
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "server"))

from app.auth import hash_password  # noqa: E402

AUTH_KEYS = ("ROOMCAM_AUTH_PASSWORD_HASH",)
REMOVED_AUTH_KEYS = ("ROOMCAM_AUTH_SESSION_SECRET",)


def main() -> int:
    password = getpass.getpass("Choose a camera password (15+ characters): ")
    if len(password) < 15:
        print("Password must contain at least 15 characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirm camera password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    values = {
        "ROOMCAM_AUTH_PASSWORD_HASH": hash_password(password, secrets.token_bytes(16)),
    }

    if len(sys.argv) == 1:
        for key in AUTH_KEYS:
            print(f"{key}={values[key]}")
        return 0
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} [ENV_FILE]", file=sys.stderr)
        return 2

    env_path = Path(sys.argv[1])
    existing_lines = env_path.read_text().splitlines() if env_path.exists() else []
    removed_keys = (*AUTH_KEYS, *REMOVED_AUTH_KEYS)
    retained_lines = [line for line in existing_lines if not any(line.startswith(f"{key}=") for key in removed_keys)]
    auth_lines = [f"{key}={values[key]}" for key in AUTH_KEYS]
    contents = "\n".join([*retained_lines, *auth_lines]) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=env_path.parent,
            prefix=f".{env_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, env_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    print(f"Updated authentication secrets in {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
