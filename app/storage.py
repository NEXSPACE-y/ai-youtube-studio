"""成果物ストレージ。local=ファイル / cloud=GCS。

命名規則(要件8章): {案件ID}/{工程}/{シーン}/v{版}/{ファイル名}
UIへの配信は両モードとも /media/{name} 経由(署名URL不要・権限は服のアプリ側で担保)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.config import settings


def object_name(project_id: str, stage: str, scene_no: Optional[int], version: int,
                filename: str) -> str:
    scene = f"scene{scene_no:03d}" if scene_no is not None else "common"
    return f"{project_id}/{stage}/{scene}/v{version}/{filename}"


class Storage(ABC):
    @abstractmethod
    def write(self, name: str, data: bytes) -> str: ...

    @abstractmethod
    def read(self, name: str) -> bytes: ...

    def url_for(self, name: str) -> str:
        return f"/media/{name}"


class LocalStorage(Storage):
    def __init__(self, base: Path):
        self.base = base / "assets"
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        p = (self.base / name).resolve()
        if not str(p).startswith(str(self.base.resolve())):
            raise ValueError("不正なパス")
        return p

    def write(self, name: str, data: bytes) -> str:
        p = self._path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return name

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()


class GCSStorage(Storage):
    def __init__(self):
        from google.cloud import storage as gcs  # 遅延import

        self._bucket = gcs.Client(project=settings.gcp_project).bucket(settings.gcs_bucket)

    def write(self, name: str, data: bytes) -> str:
        self._bucket.blob(name).upload_from_string(data)
        return name

    def read(self, name: str) -> bytes:
        return self._bucket.blob(name).download_as_bytes()


_storage: Optional[Storage] = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(settings.data_dir) if settings.is_local else GCSStorage()
    return _storage
