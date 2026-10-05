from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AIResearchSource,
    AIWritingImage,
    AIWritingJob,
    AIWritingMessage,
    AIWritingSession,
)
from app.services.ai_writer import (
    AIWriterError,
    OpenAICompatibleWriter,
    enforce_selected_citations,
)


logger = logging.getLogger(__name__)
TERMINAL_JOB_STATUSES = {'succeeded', 'partial', 'failed'}
ACTIVE_JOB_STATUSES = {'queued', 'running'}


def serialize_job(job: AIWritingJob) -> dict:
    return {
        'id': job.id,
        'session_id': job.session_id,
        'type': job.job_type,
        'status': job.status,
        'phase': job.phase,
        'progress': job.progress,
        'error': job.error or '',
        'attempts': job.attempts,
        'created_at': job.created_at.isoformat(),
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'updated_at': job.updated_at.isoformat(),
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
    }


def enqueue_finalize_job(
    db: Session,
    *,
    session: AIWritingSession,
    author_id: int,
    payload: dict,
) -> AIWritingJob:
    active = db.query(AIWritingJob).filter(
        AIWritingJob.session_id == session.id,
        AIWritingJob.status.in_(ACTIVE_JOB_STATUSES),
    ).first()
    if active:
        return active
    job = AIWritingJob(
        session_id=session.id,
        author_id=author_id,
        job_type='finalize',
        status='queued',
        phase='queued',
        progress=0,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    session.status = 'final_queued'
    session.last_error = ''
    db.add(job)
    db.commit()
    db.refresh(job)
    ai_job_worker.notify()
    return job


def _selected_sources(db: Session, session_id: int) -> list[dict[str, str]]:
    rows = db.query(AIResearchSource).filter(
        AIResearchSource.session_id == session_id,
        AIResearchSource.selected.is_(True),
    ).order_by(AIResearchSource.id.asc()).limit(8).all()
    return [{
        'title': row.title,
        'url': row.url,
        'snippet': row.snippet,
        'content': row.source_content,
        'source_name': row.source_name,
        'published_at': row.published_at,
    } for row in rows]


def _claim_specific_job(db: Session, job_id: int) -> bool:
    current = db.query(AIWritingJob).filter(
        AIWritingJob.id == job_id,
        AIWritingJob.status == 'queued',
    ).first()
    if not current or current.attempts >= settings.AI_JOB_MAX_ATTEMPTS:
        return False
    now = datetime.utcnow()
    progress = max(current.progress or 0, 5)
    phase = 'planning_images' if progress >= 70 else 'generating_article'
    updated = db.query(AIWritingJob).filter(
        AIWritingJob.id == job_id,
        AIWritingJob.status == 'queued',
        AIWritingJob.attempts < settings.AI_JOB_MAX_ATTEMPTS,
    ).update({
        AIWritingJob.status: 'running',
        AIWritingJob.phase: phase,
        AIWritingJob.progress: progress,
        AIWritingJob.started_at: now,
        AIWritingJob.updated_at: now,
        AIWritingJob.attempts: AIWritingJob.attempts + 1,
        AIWritingJob.error: '',
    }, synchronize_session=False)
    db.commit()
    return bool(updated)


def claim_next_job(session_factory: Callable[[], Session] = SessionLocal) -> int | None:
    db = session_factory()
    try:
        candidates = db.query(AIWritingJob.id).filter(
            AIWritingJob.status == 'queued',
            AIWritingJob.attempts < settings.AI_JOB_MAX_ATTEMPTS,
        ).order_by(AIWritingJob.created_at.asc()).limit(5).all()
        for (job_id,) in candidates:
            if _claim_specific_job(db, job_id):
                return job_id
        return None
    finally:
        db.close()


def _fail_article_job(
    job_id: int,
    message: str,
    session_factory: Callable[[], Session],
) -> None:
    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job:
            return
        job.status = 'failed'
        job.phase = 'failed'
        job.error = message[:2000]
        job.finished_at = datetime.utcnow()
        job.progress = 100
        job.session.status = 'error'
        job.session.last_error = message[:2000]
        db.commit()
    finally:
        db.close()


def _partial_image_job(
    job_id: int,
    message: str,
    session_factory: Callable[[], Session],
) -> None:
    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job:
            return
        detail = f'最终稿已生成，但配图计划失败：{message}'[:2000]
        job.status = 'partial'
        job.phase = 'completed_with_warning'
        job.error = detail
        job.finished_at = datetime.utcnow()
        job.progress = 100
        job.session.status = 'final_ready'
        job.session.last_error = detail
        db.commit()
    finally:
        db.close()


def _persist_article(
    job_id: int,
    result: dict,
    allowed_urls: list[str],
    session_factory: Callable[[], Session],
) -> None:
    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job:
            return
        content, warnings = enforce_selected_citations(result['content'], allowed_urls)
        writing_session = job.session
        writing_session.final_title = result['title']
        writing_session.final_content = content
        writing_session.pre_humanized_title = ''
        writing_session.pre_humanized_content = ''
        writing_session.humanize_summary = ''
        writing_session.citation_warnings = json.dumps(warnings, ensure_ascii=False)
        writing_session.status = 'planning_images'
        writing_session.last_error = ''
        for image in writing_session.images:
            image.status = 'obsolete'
        db.add(AIWritingMessage(
            session_id=writing_session.id,
            role='assistant',
            message_type='final',
            content='最终候选稿已经生成并保存，后台正在规划配图。',
        ))
        job.phase = 'article_ready'
        job.progress = 70
        job.result_json = json.dumps({'title': result['title']}, ensure_ascii=False)
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _persist_image_plan(
    job_id: int,
    result: dict,
    session_factory: Callable[[], Session],
) -> None:
    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job:
            return
        writing_session = job.session
        writing_session.final_content = result['content']
        existing = {image.slot: image for image in writing_session.images}
        active_slots = set()
        for plan in result['images']:
            active_slots.add(plan.slot)
            image = existing.get(plan.slot)
            if image is None:
                image = AIWritingImage(session_id=writing_session.id, slot=plan.slot)
                db.add(image)
            prompt_changed = image.prompt != plan.prompt
            image.image_type = plan.image_type
            image.prompt = plan.prompt
            image.alt_text = plan.alt_text
            image.placement_heading = plan.placement_heading
            image.aspect_ratio = plan.aspect_ratio
            image.error = ''
            if prompt_changed or not image.file_path:
                image.status = 'planned'
                image.file_path = ''
        for slot, image in existing.items():
            if slot not in active_slots:
                image.status = 'obsolete'
        db.add(AIWritingMessage(
            session_id=writing_session.id,
            role='assistant',
            message_type='image_plan',
            content=f'已为最终稿规划 {len(result["images"])} 张配图。',
        ))
        writing_session.status = 'final_ready'
        writing_session.last_error = ''
        job.status = 'succeeded'
        job.phase = 'completed'
        job.progress = 100
        job.error = ''
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _complete_without_images(
    job_id: int,
    session_factory: Callable[[], Session],
) -> None:
    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job:
            return
        job.status = 'succeeded'
        job.phase = 'completed'
        job.progress = 100
        job.error = ''
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        job.session.status = 'final_ready'
        job.session.last_error = ''
        db.commit()
    finally:
        db.close()


def process_job(
    job_id: int,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    writer_factory: Callable[[], OpenAICompatibleWriter] = OpenAICompatibleWriter,
    already_claimed: bool = False,
) -> None:
    db = session_factory()
    try:
        if not already_claimed and not _claim_specific_job(db, job_id):
            return
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job or job.status != 'running':
            return
        payload = json.loads(job.payload_json or '{}')
        writing_session = job.session
        resume_from_article = job.progress >= 70 and bool(writing_session.final_content)
        if not resume_from_article:
            recent = db.query(AIWritingMessage).filter(
                AIWritingMessage.session_id == writing_session.id,
            ).order_by(AIWritingMessage.id.desc()).limit(8).all()
            sources = _selected_sources(db, writing_session.id)
            article_args = {
                'topic': writing_session.topic,
                'core_points': writing_session.core_points,
                'current_content': payload.get('current_content') or writing_session.current_content,
                'confirmed_brief': payload.get('confirmed_brief') or writing_session.confirmed_brief,
                'recent_messages': [
                    {'role': item.role, 'content': item.content}
                    for item in reversed(recent)
                ],
                'research_sources': sources,
                'writing_mode': payload.get('writing_mode') or writing_session.writing_mode,
                'style_notes': payload.get('style_notes') or writing_session.style_notes,
            }
            allowed_urls = [source['url'] for source in sources]
        else:
            article_args = None
            allowed_urls = []
        db.commit()
    finally:
        db.close()

    writer = writer_factory()
    if article_args is not None:
        try:
            article = writer.generate_final_article(**article_args)
        except AIWriterError as exc:
            _fail_article_job(job_id, str(exc), session_factory)
            return
        _persist_article(job_id, article, allowed_urls, session_factory)

    db = session_factory()
    try:
        job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).first()
        if not job or job.status != 'running':
            return
        payload = json.loads(job.payload_json or '{}')
        writing_session = job.session
        include_cover = bool(payload.get('include_cover', True))
        inline_count = min(
            max(0, int(payload.get('inline_image_count', 2))),
            settings.AI_MAX_INLINE_IMAGES,
        )
        if not include_cover and inline_count <= 0:
            image_args = None
        else:
            image_args = {
                'topic': writing_session.topic,
                'title': writing_session.final_title or writing_session.draft_title or writing_session.topic,
                'content': writing_session.final_content,
                'include_cover': include_cover,
                'inline_image_count': inline_count,
                'image_style': payload.get('image_style') or '克制的现代科技插画',
            }
        job.phase = 'planning_images'
        job.progress = 75
        job.updated_at = datetime.utcnow()
        writing_session.status = 'planning_images'
        db.commit()
    finally:
        db.close()

    if image_args is None:
        _complete_without_images(job_id, session_factory)
        return
    try:
        image_plan = writer.plan_images(**image_args)
    except AIWriterError as exc:
        _partial_image_job(job_id, str(exc), session_factory)
        return
    _persist_image_plan(job_id, image_plan, session_factory)


def recover_stale_jobs(session_factory: Callable[[], Session] = SessionLocal) -> int:
    db = session_factory()
    recovered = 0
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=settings.AI_JOB_STALE_SECONDS)
        jobs = db.query(AIWritingJob).filter(
            AIWritingJob.status == 'running',
            AIWritingJob.updated_at < cutoff,
        ).all()
        for job in jobs:
            if job.attempts >= settings.AI_JOB_MAX_ATTEMPTS:
                job.status = 'failed'
                job.phase = 'failed'
                job.progress = 100
                job.error = '后台任务多次中断，请重新提交最终稿生成。'
                job.finished_at = datetime.utcnow()
                job.session.status = 'error'
                job.session.last_error = job.error
            else:
                job.status = 'queued'
                job.phase = 'queued' if job.progress < 70 else 'article_ready'
                job.session.status = 'final_queued' if job.progress < 70 else 'planning_images'
                recovered += 1
        db.commit()
        return recovered
    finally:
        db.close()


class AIJobWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self) -> None:
        if not settings.AI_JOB_WORKER_ENABLED:
            return
        if self._thread and self._thread.is_alive():
            return
        recover_stale_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='ai-writing-worker', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def notify(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = claim_next_job()
                if job_id is not None:
                    process_job(job_id, already_claimed=True)
                    continue
            except Exception:
                logger.exception('AI writing worker iteration failed')
            self._wake.wait(settings.AI_JOB_POLL_INTERVAL)
            self._wake.clear()


ai_job_worker = AIJobWorker()
