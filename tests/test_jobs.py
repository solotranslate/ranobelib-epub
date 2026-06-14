from ranobelib_epub.epub import BookMetadata
from ranobelib_epub.inventory import ChapterBranchVariant
from ranobelib_epub.jobs import BuildJobManager, BuildJobRequest, BuildJobSnapshot
from ranobelib_epub.ranobelib import parse_title_url


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_job_progress_snapshot_and_cleanup_are_clock_driven() -> None:
    clock = ManualClock()
    manager = BuildJobManager(clock=clock, completed_ttl_seconds=10)
    job_id = "job"
    manager._jobs[job_id] = BuildJobSnapshot(
        job_id=job_id,
        status="queued",
        message="Queued",
        created_at=clock(),
        updated_at=clock(),
    )

    manager.update(
        job_id,
        status="fetching_chapters",
        message="Fetching chapter 1 of 2",
        chapter_current=1,
        chapter_total=2,
    )

    snapshot = manager.get(job_id)
    assert snapshot is not None
    assert snapshot.public_dict()["status"] == "fetching_chapters"
    assert snapshot.public_dict()["chapter_total"] == 2

    manager.update(job_id, status="ready", message="Ready", epub_bytes=b"epub")
    clock.advance(11)
    assert manager.get(job_id) is None


def test_concurrency_guard_rejects_second_active_job() -> None:
    clock = ManualClock()
    manager = BuildJobManager(clock=clock, max_active_jobs=1)
    request = BuildJobRequest(
        title=parse_title_url("https://ranobelib.me/ru/book/1--demo"),
        metadata=BookMetadata(title="Demo"),
        variants=(
            ChapterBranchVariant(
                external_chapter_id=1,
                branch_id=None,
                volume="1",
                number="1",
                number_secondary=None,
                chapter_title=None,
                is_default_branch=True,
            ),
        ),
        include_images=True,
        filename="demo.epub",
    )
    manager._jobs["active"] = BuildJobSnapshot(
        job_id="active",
        status="fetching_images",
        message="Fetching images",
        created_at=clock(),
        updated_at=clock(),
    )

    try:
        manager.start(request, service=object())  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "Сервис сейчас занят. Попробуйте чуть позже." in str(exc)
    else:
        raise AssertionError("Expected concurrency guard to reject active job")


def test_cancel_active_job_marks_cancelled_and_hides_epub_bytes() -> None:
    clock = ManualClock()
    manager = BuildJobManager(clock=clock)
    job_id = "active"
    manager._jobs[job_id] = BuildJobSnapshot(
        job_id=job_id,
        status="fetching_chapters",
        message="Fetching",
        created_at=clock(),
        updated_at=clock(),
        epub_bytes=b"partial",
    )

    snapshot, message, status_code = manager.cancel(job_id)

    assert status_code == 200
    assert message == "Сборка остановлена."
    assert snapshot is not None
    assert snapshot.status == "cancelled"
    assert snapshot.epub_bytes is None
    public = snapshot.public_dict()
    assert public["status"] == "cancelled"
    assert public["message"] == "Сборка остановлена."
    assert "download_url" not in public


def test_cancel_non_active_jobs_returns_controlled_russian_messages() -> None:
    clock = ManualClock()
    manager = BuildJobManager(clock=clock)
    for status, expected in (
        ("ready", "Сборка уже завершена, остановка невозможна."),
        ("failed", "Сборка уже завершилась ошибкой, остановка невозможна."),
        ("cancelled", "Сборка уже остановлена."),
    ):
        manager._jobs[status] = BuildJobSnapshot(
            job_id=status,
            status=status,  # type: ignore[arg-type]
            message="Done",
            created_at=clock(),
            updated_at=clock(),
        )
        _snapshot, message, status_code = manager.cancel(status)
        assert status_code == 409
        assert message == expected

    _snapshot, message, status_code = manager.cancel("missing")
    assert status_code == 404
    assert message == "Задача сборки не найдена или устарела."
