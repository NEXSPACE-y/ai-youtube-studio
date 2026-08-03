"""案件データの保存層。ローカルはJSONファイル、クラウドはFirestore。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import Project


class ProjectRepo(ABC):
    @abstractmethod
    def get(self, project_id: str) -> Optional[Project]: ...

    @abstractmethod
    def save(self, project: Project) -> None: ...

    @abstractmethod
    def list_all(self) -> list[Project]: ...


class LocalJsonRepo(ProjectRepo):
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "projects"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return self.dir / f"{project_id}.json"

    def get(self, project_id: str) -> Optional[Project]:
        p = self._path(project_id)
        if not p.exists():
            return None
        return Project.model_validate_json(p.read_text(encoding="utf-8"))

    def save(self, project: Project) -> None:
        self._path(project.id).write_text(
            json.dumps(project.model_dump(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def list_all(self) -> list[Project]:
        projects = [
            Project.model_validate_json(f.read_text(encoding="utf-8"))
            for f in sorted(self.dir.glob("*.json"))
        ]
        return sorted(projects, key=lambda p: p.created_at, reverse=True)


class FirestoreRepo(ProjectRepo):
    COLLECTION = "projects"

    def __init__(self, gcp_project: str) -> None:
        from google.cloud import firestore  # クラウドモードでのみimport

        self.db = firestore.Client(project=gcp_project)

    def get(self, project_id: str) -> Optional[Project]:
        doc = self.db.collection(self.COLLECTION).document(project_id).get()
        if not doc.exists:
            return None
        return Project.model_validate(doc.to_dict())

    def save(self, project: Project) -> None:
        self.db.collection(self.COLLECTION).document(project.id).set(project.model_dump())

    def list_all(self) -> list[Project]:
        docs = (
            self.db.collection(self.COLLECTION)
            .order_by("created_at", direction="DESCENDING")
            .stream()
        )
        return [Project.model_validate(d.to_dict()) for d in docs]


_repo: Optional[ProjectRepo] = None


def get_repo() -> ProjectRepo:
    global _repo
    if _repo is None:
        if settings.is_local:
            _repo = LocalJsonRepo(settings.data_dir)
        else:
            _repo = FirestoreRepo(settings.gcp_project)
    return _repo
