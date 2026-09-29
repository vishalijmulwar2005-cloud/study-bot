"""StorageService abstraction (Phase 2).

Providers can be swapped (S3/GCS) without touching application logic.
The MVP implementation stores binaries privately on the local filesystem
under a server-generated random key; the directory is never exposed through
any static route (Security spec §05).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class StorageError(Exception):
    """Raised when the storage backend cannot complete an operation."""


class StorageService(ABC):
    @abstractmethod
    def save(self, data: bytes) -> str:
        """Persist bytes and return a private storage key."""

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Return the bytes stored under `key`."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object. Must be idempotent (missing key is fine)."""


class LocalFileStorage(StorageService):
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path_for(self, key: str) -> Path:
        # Key is server-generated; refuse anything that could traverse.
        if "/" in key or ".." in key or key.startswith("."):
            raise StorageError("invalid storage key")
        return self.root / key

    def save(self, data: bytes) -> str:
        key = uuid.uuid4().hex
        path = self._path_for(key)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"failed to persist object: {exc.__class__.__name__}") from exc
        return key

    def load(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError("object not found") from exc
        except OSError as exc:
            raise StorageError(f"failed to read object: {exc.__class__.__name__}") from exc

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"failed to delete object: {exc.__class__.__name__}") from exc
