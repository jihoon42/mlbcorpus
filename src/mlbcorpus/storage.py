"""원본 응답의 gzip 캐시. 받은 바이트를 그대로, 원자적으로 쓴다."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any


def write_gz_atomic(path: Path, data: bytes, *, compresslevel: int = 6) -> int:
    """tmp 파일에 쓴 뒤 rename. 중간에 죽어도 반쪽짜리 파일이 남지 않는다. 반환값은 저장 크기(bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with gzip.open(tmp, "wb", compresslevel=compresslevel) as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path.stat().st_size


def read_gz_bytes(path: Path) -> bytes:
    with gzip.open(path, "rb") as f:
        return f.read()


def read_gz_json(path: Path) -> Any:
    return json.loads(read_gz_bytes(path))
