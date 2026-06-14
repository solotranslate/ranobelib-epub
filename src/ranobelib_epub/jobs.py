from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Literal, Protocol

from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import ChapterBranchVariant
from ranobelib_epub.ranobelib import RanobeLibTitleUrl

JobStatus = Literal[
    "queued",
    "starting",
    "fetching_chapters",
    "fetching_images",
    "building_epub",
    "ready",
    "failed",
]


class ProgressBuildService(Protocol):
    def build(
        self,
        title: RanobeLibTitleUrl,
        metadata: BookMetadata,
        variants: tuple[ChapterBranchVariant, ...],
        *,
        include_images: bool = False,
        progress_callback: Callable[..., None] | None = None,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BuildJobSnapshot:
    job_id: str
    status: JobStatus
    message: str
    created_at: float
    updated_at: float
    chapter_current: int | None = None
    chapter_total: int | None = None
    image_current: int | None = None
    image_total: int | None = None
    epub_bytes: bytes | None = None
    filename: str | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "job_id": self.job_id,
            "status": self.status,
            "message": self.message,
        }
        for name in ("chapter_current", "chapter_total", "image_current", "image_total"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        if self.status == "ready":
            payload["download_url"] = f"/build-jobs/{self.job_id}/download"
        if self.status == "failed" and self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True, slots=True)
class BuildJobRequest:
    title: RanobeLibTitleUrl
    metadata: BookMetadata
    variants: tuple[ChapterBranchVariant, ...]
    include_images: bool
    filename: str


class BuildJobManager:
    def __init__(
        self,
        *,
        max_active_jobs: int = 1,
        completed_ttl_seconds: float = 30 * 60,
        running_timeout_seconds: float = 60 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_active_jobs = max_active_jobs
        self.completed_ttl_seconds = completed_ttl_seconds
        self.running_timeout_seconds = running_timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, BuildJobSnapshot] = {}

    def start(self, request: BuildJobRequest, service: ProgressBuildService) -> str:
        with self._lock:
            self.cleanup()
            if self._active_count_locked() >= self.max_active_jobs:
                raise RuntimeError(
                    "Сервис сейчас занят. Попробуйте чуть позже."
                )
            now = self._clock()
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = BuildJobSnapshot(
                job_id=job_id,
                status="queued",
                message="Задача поставлена в очередь; ожидаю начала сборки EPUB.",
                created_at=now,
                updated_at=now,
                filename=request.filename,
            )
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, request, service),
            name=f"epub-build-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return job_id

    def get(self, job_id: str) -> BuildJobSnapshot | None:
        with self._lock:
            self.cleanup()
            return self._jobs.get(job_id)

    def cleanup(self) -> None:
        now = self._clock()
        expired: list[str] = []
        for job_id, job in self._jobs.items():
            if job.status in {"ready", "failed"}:
                if now - job.updated_at > self.completed_ttl_seconds:
                    expired.append(job_id)
            elif now - job.updated_at > self.running_timeout_seconds:
                expired.append(job_id)
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def _run_job(
        self, job_id: str, request: BuildJobRequest, service: ProgressBuildService
    ) -> None:
        def progress(status: JobStatus, **updates: object) -> None:
            self.update(job_id, status=status, **updates)

        try:
            progress("starting", message="Начинаю сборку EPUB.")
            epub_bytes = service.build(
                request.title,
                request.metadata,
                request.variants,
                include_images=request.include_images,
                progress_callback=progress,
            )
            self.update(
                job_id,
                status="ready",
                message="EPUB готов к скачиванию.",
                epub_bytes=epub_bytes,
            )
        except Exception as exc:  # noqa: BLE001 - background job must return controlled status.
            self.update(
                job_id,
                status="failed",
                message="Сборка EPUB не удалась.",
                error=str(exc) or "Сборка не удалась.",
            )

    def update(self, job_id: str, *, status: JobStatus, **updates: object) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return
            allowed = {
                "message",
                "chapter_current",
                "chapter_total",
                "image_current",
                "image_total",
                "epub_bytes",
                "error",
            }
            data = {key: value for key, value in updates.items() if key in allowed}
            self._jobs[job_id] = replace(
                current, status=status, updated_at=self._clock(), **data
            )

    def _active_count_locked(self) -> int:
        return sum(
            1 for job in self._jobs.values() if job.status not in {"ready", "failed"}
        )

