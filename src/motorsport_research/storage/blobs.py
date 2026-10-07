"""Content-addressed raw document storage with integrity checks and atomic writes."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from motorsport_research.storage.database import StorageError


class BlobStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise StorageError("Invalid document content hash")
        return self.root / digest[:2] / f"{digest}.bin"

    def read(self, digest: str) -> bytes:
        path = self.path(digest)
        if path.is_symlink():
            raise StorageError("Stored document must not be a symbolic link")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise StorageError("Stored document is missing or unreadable") from error
        if hashlib.sha256(content).hexdigest() != digest:
            raise StorageError("Stored document content does not match its hash")
        return content

    def put(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        target = self.path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            self.read(digest)
            return digest
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            if os.name == "posix":
                for directory in (target.parent, self.root):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return digest
