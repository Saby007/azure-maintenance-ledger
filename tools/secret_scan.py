"""Minimal secret scan for CI: fails on keys, SAS tokens, connection strings and private keys in tracked-style files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "dist", "reports", "cache", "__pycache__", ".pytest_cache", ".ruff_cache", "exports", "node_modules"}
SKIP_FILES = {".env", "local.settings.json", "pirs.json", "pirs.json.bak"}  # PIR fixtures are public text
EXT = {".py", ".ps1", ".bicep", ".json", ".yaml", ".yml", ".md", ".kql", ".csv", ".toml", ".txt", ".example", ".cfg"}

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "storage account key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "connection string secret": re.compile(r"(?i)(?:SharedAccessKey|Password|Pwd)=[^;\s'\"]{6,}"),
    "SAS token": re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{20,}"),
    "bearer token": re.compile(r"(?i)bearer\s+eyJ[A-Za-z0-9_-]{20,}"),
    "client secret assignment": re.compile(r"(?i)(?:client_secret|clientsecret|api[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9~._-]{16,}['\"]"),
}


def scan(root: Path = ROOT) -> list[str]:
    hits: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts) or p.name in SKIP_FILES:
            continue
        if p.suffix.lower() not in EXT and p.name not in {".gitignore", ".env.example"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(root)}:{line}: {label}")
    return hits


def main() -> int:
    hits = scan()
    for h in hits:
        print(h)
    print(f"secret scan: {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
