import hashlib
from pathlib import Path


class AssetManifest:
    """Content hashes for every static file, so URLs change whenever a file does."""

    def __init__(self, static_dir: Path):
        self.static_dir = Path(static_dir)
        self.hashes: dict[str, str] = {}
        for path in sorted(self.static_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(self.static_dir).as_posix()
                self.hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:10]

    def url(self, path: str) -> str:
        return f"/static/{path}?v={self.hashes[path]}"
