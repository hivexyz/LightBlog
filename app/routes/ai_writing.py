from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import (
    get_csrf_nonce,
    get_session_id,
    require_admin,
    verify_csrf_token,
)
from app.config import settings
from app.database import get_db
from app.models import (
    AIResearchSource,
    AIWritingImage,
    AIWritingJob,
    AIWritingMessage,
    AIWritingSession,
    Post,
    User,
)
from app.services.ai_writer import (
    AIWriterError,
    OpenAICompatibleWriter,
    assemble_final_content,
    enforce_selected_citations,
    save_generated_image,
)
from app.services.web_search import WebSearchError, get_search_provider
from app.services.ai_job_worker import (
    ACTIVE_JOB_STATUSES,
    enqueue_finalize_job,
    serialize_job,
)


router = APIRouter(prefix='/admin/ai-writing', tags=['ai-writing'])
BUSY_STATUSES = {
    'planning_research', 'searching', 'generating_draft', 'interviewing',
    'final_queued', 'finalizing', 'planning_images', 'humanizing'
}

WritingMode = Literal[
    'personal_opinion', 'technical_tutorial', 'problem_review', 'debate', 'research_notes'
]


class SessionCreateRequest(BaseModel):
    post_id: Optional[int] = None
    topic: str = Field(min_length=1, max_length=500)
    core_points: str = Field(min_length=1, max_length=12000)
    target_audience: str = Field(default='', max_length=300)
    desired_length: str = Field(default='中等', max_length=50)
    writing_mode: WritingMode = 'personal_opinion'
    style_notes: str = Field(default='', max_length=3000)
    source_content: str = Field(default='', max_length=100000)


class InterviewRequest(BaseModel):
    user_message: str = Field(default='', max_length=6000)
    confirmed_brief: str = Field(default='', max_length=12000)
    current_content: str = Field(default='', max_length=100000)


class DraftRequest(BaseModel):
    current_content: str = Field(default='', max_length=100000)
    writing_mode: WritingMode = 'personal_opinion'
    style_notes: str = Field(default='', max_length=3000)


class FinalizeRequest(BaseModel):
    current_content: str = Field(min_length=1, max_length=100000)
    confirmed_brief: str = Field(default='', max_length=12000)
    writing_mode: WritingMode = 'personal_opinion'
    style_notes: str = Field(default='', max_length=3000)
    include_cover: bool = True
    inline_image_count: int = Field(default=2, ge=0, le=6)
    image_style: str = Field(default='克制的现代科技插画', max_length=200)


class ImagePlanRequest(BaseModel):
    include_cover: bool = True
    inline_image_count: int = Field(default=2, ge=0, le=6)
    image_style: str = Field(default='克制的现代科技插画', max_length=200)


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(default='', max_length=4000)


class ResearchPlanRequest(BaseModel):
    focus: str = Field(default='', max_length=3000)
    current_content: str = Field(default='', max_length=100000)


class ResearchSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    purpose: str = Field(default='', max_length=500)


class ResearchSelectionRequest(BaseModel):
    selected: bool


def _require_csrf(request: Request, token: str) -> None:
    nonce = get_csrf_nonce(get_session_id(request))
    if not verify_csrf_token(token, nonce):
        raise HTTPException(status_code=400, detail='CSRF token 无效')


def _get_owned_session(db: Session, session_id: int, user: User) -> AIWritingSession:
    session = db.query(AIWritingSession).filter(
        AIWritingSession.id == session_id,
        AIWritingSession.author_id == user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail='写作会话不存在')
    return session


def _claim_session(db: Session, session_id: int, user_id: int, next_status: str) -> None:
    stale_before = datetime.utcnow() - timedelta(seconds=max(settings.AI_REQUEST_TIMEOUT * 2, 180))
    updated = db.query(AIWritingSession).filter(
        AIWritingSession.id == session_id,
        AIWritingSession.author_id == user_id,
        or_(
            ~AIWritingSession.status.in_(BUSY_STATUSES),
            AIWritingSession.updated_at < stale_before,
        ),
    ).update({
        AIWritingSession.status: next_status,
        AIWritingSession.last_error: '',
    }, synchronize_session=False)
    db.commit()
    if not updated:
        raise HTTPException(status_code=409, detail='该会话正在生成，请等待当前操作完成')


def _fail_session(db: Session, session_id: int, message: str) -> None:
    db.query(AIWritingSession).filter(AIWritingSession.id == session_id).update({
        AIWritingSession.status: 'error',
        AIWritingSession.last_error: message[:2000],
    }, synchronize_session=False)
    db.commit()


def _raise_provider_error(exc: AIWriterError) -> None:
    status_code = 503 if '未配置' in str(exc) else 502
    raise HTTPException(status_code=status_code, detail=str(exc))


def _active_images(session: AIWritingSession) -> list[AIWritingImage]:
    return [image for image in session.images if image.status != 'obsolete']


def _json_list(raw: str) -> list:
    try:
        value = json.loads(raw or '[]')
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _selected_sources(db: Session, session_id: int) -> list[dict[str, str]]:
    sources = db.query(AIResearchSource).filter(
        AIResearchSource.session_id == session_id,
        AIResearchSource.selected.is_(True),
    ).order_by(AIResearchSource.id.asc()).limit(8).all()
    return [
        {
            'title': source.title,
            'url': source.url,
            'snippet': source.snippet,
            'content': source.source_content,
            'source_name': source.source_name,
            'published_at': source.published_at,
        }
        for source in sources
    ]


def _serialize_session(session: AIWritingSession) -> dict:
    images = _active_images(session)
    assembled = assemble_final_content(session.final_content, images)
    active_job = next(
        (job for job in reversed(session.jobs) if job.status in ACTIVE_JOB_STATUSES),
        None,
    )
    return {
        'id': session.id,
        'post_id': session.post_id,
        'topic': session.topic,
        'core_points': session.core_points,
        'target_audience': session.target_audience,
        'desired_length': session.desired_length,
        'writing_mode': session.writing_mode,
        'style_notes': session.style_notes,
        'draft_title': session.draft_title,
        'final_title': session.final_title,
        'initial_draft': session.initial_draft,
        'current_content': session.current_content,
        'final_content': session.final_content,
        'pre_humanized_title': session.pre_humanized_title,
        'pre_humanized_content': session.pre_humanized_content,
        'humanize_summary': session.humanize_summary,
        'assembled_content': assembled,
        'confirmed_brief': session.confirmed_brief,
        'status': session.status,
        'last_error': session.last_error,
        'text_enabled': settings.AI_TEXT_ENABLED,
        'image_enabled': settings.AI_IMAGE_ENABLED,
        'web_search_enabled': settings.WEB_SEARCH_ENABLED,
        'research_queries': _json_list(session.research_queries),
        'citation_warnings': _json_list(session.citation_warnings),
        'active_job': serialize_job(active_job) if active_job else None,
        'messages': [
            {
                'id': message.id,
                'role': message.role,
                'message_type': message.message_type,
                'content': message.content,
                'created_at': message.created_at.isoformat(),
            }
            for message in session.messages
        ],
        'images': [
            {
                'id': image.id,
                'slot': image.slot,
                'type': image.image_type,
                'prompt': image.prompt,
                'alt': image.alt_text,
                'after_heading': image.placement_heading,
                'aspect_ratio': image.aspect_ratio,
                'status': image.status,
                'url': image.file_path,
                'error': image.error,
            }
            for image in images
        ],
        'research_sources': [
            {
                'id': source.id,
                'query': source.query,
                'purpose': source.purpose,
                'title': source.title,
                'url': source.url,
                'snippet': source.snippet,
                'source_name': source.source_name,
                'published_at': source.published_at,
                'retrieved_at': source.retrieved_at.isoformat(),
                'selected': source.selected,
                'status': source.fetch_status,
            }
            for source in session.research_sources
        ],
        'created_at': session.created_at.isoformat(),
        'updated_at': session.updated_at.isoformat(),
    }


@router.post('/sessions')
def create_session(
    payload: SessionCreateRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    if payload.post_id is not None:
        post = db.query(Post).filter(Post.id == payload.post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail='文章不存在')
    session = AIWritingSession(
        post_id=payload.post_id,
        author_id=user.id,
        topic=payload.topic.strip(),
        core_points=payload.core_points.strip(),
        target_audience=payload.target_audience.strip(),
        desired_length=payload.desired_length.strip() or '中等',
        writing_mode=payload.writing_mode,
        style_notes=payload.style_notes.strip(),
        current_content=payload.source_content.strip(),
        status='created',
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.get('/sessions/{session_id}')
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    return _serialize_session(_get_owned_session(db, session_id, user))


@router.post('/sessions/{session_id}/draft')
def generate_draft(
    session_id: int,
    payload: DraftRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if payload.current_content.strip():
        session.current_content = payload.current_content.strip()
    session.writing_mode = payload.writing_mode
    session.style_notes = payload.style_notes.strip()
    db.commit()
    _claim_session(db, session.id, user.id, 'generating_draft')
    session = _get_owned_session(db, session_id, user)
    sources = _selected_sources(db, session.id)
    writer_args = {
        'topic': session.topic,
        'core_points': session.core_points,
        'target_audience': session.target_audience,
        'desired_length': session.desired_length,
        'source_content': session.current_content,
        'research_sources': sources,
        'writing_mode': session.writing_mode,
        'style_notes': session.style_notes,
    }
    db.commit()
    try:
        result = OpenAICompatibleWriter().generate_draft(**writer_args)
    except AIWriterError as exc:
        _fail_session(db, session_id, str(exc))
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    content, warnings = enforce_selected_citations(
        result['content'], [source['url'] for source in sources]
    )
    session.draft_title = result['title']
    session.initial_draft = content
    session.current_content = content
    session.citation_warnings = json.dumps(warnings, ensure_ascii=False)
    session.status = 'draft_ready'
    session.last_error = ''
    db.add(AIWritingMessage(
        session_id=session.id,
        role='assistant',
        message_type='draft',
        content='初稿已经生成。接下来我会通过采访补足真实经历、反例和适用边界。',
    ))
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/interview')
def interview(
    session_id: int,
    payload: InterviewRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if not session.current_content:
        raise HTTPException(status_code=409, detail='请先生成初稿')
    if payload.user_message.strip():
        db.add(AIWritingMessage(
            session_id=session.id,
            role='user',
            message_type='answer',
            content=payload.user_message.strip(),
        ))
        db.commit()
    if payload.current_content.strip():
        session.current_content = payload.current_content.strip()
        db.commit()
    if payload.confirmed_brief.strip():
        session.confirmed_brief = payload.confirmed_brief.strip()
        db.commit()

    _claim_session(db, session.id, user.id, 'interviewing')
    session = _get_owned_session(db, session_id, user)
    recent = db.query(AIWritingMessage).filter(
        AIWritingMessage.session_id == session.id,
    ).order_by(AIWritingMessage.id.desc()).limit(8).all()
    recent_messages = [
        {'role': item.role, 'content': item.content}
        for item in reversed(recent)
    ]
    sources = _selected_sources(db, session.id)
    writer_args = {
        'topic': session.topic,
        'core_points': session.core_points,
        'current_content': session.current_content,
        'confirmed_brief': session.confirmed_brief,
        'recent_messages': recent_messages,
        'user_message': payload.user_message,
        'research_sources': sources,
    }
    db.commit()
    try:
        result = OpenAICompatibleWriter().interview(**writer_args)
    except AIWriterError as exc:
        _fail_session(db, session_id, str(exc))
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    response_parts = [result['reply']] if result['reply'] else []
    response_parts.extend(f'{index}. {question}' for index, question in enumerate(result['questions'], 1))
    assistant_content = '\n\n'.join(response_parts) or '目前没有需要继续确认的问题。'
    assistant_content, _ = enforce_selected_citations(
        assistant_content, [source['url'] for source in sources]
    )
    db.add(AIWritingMessage(
        session_id=session.id,
        role='assistant',
        message_type='question',
        content=assistant_content,
    ))
    session.confirmed_brief = result['confirmed_brief']
    session.status = 'interview_ready'
    session.last_error = ''
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/finalize')
def finalize(
    session_id: int,
    payload: FinalizeRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    session.current_content = payload.current_content.strip()
    session.confirmed_brief = payload.confirmed_brief.strip()
    session.writing_mode = payload.writing_mode
    session.style_notes = payload.style_notes.strip()
    db.commit()
    job = enqueue_finalize_job(
        db,
        session=session,
        author_id=user.id,
        payload={
            'current_content': session.current_content,
            'confirmed_brief': session.confirmed_brief,
            'writing_mode': session.writing_mode,
            'style_notes': session.style_notes,
            'include_cover': payload.include_cover,
            'inline_image_count': min(payload.inline_image_count, settings.AI_MAX_INLINE_IMAGES),
            'image_style': payload.image_style,
        },
    )
    return JSONResponse(status_code=202, content={'job': serialize_job(job)})


@router.get('/jobs/{job_id}')
def get_writing_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    job = db.query(AIWritingJob).filter(
        AIWritingJob.id == job_id,
        AIWritingJob.author_id == user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail='生成任务不存在')
    result = {'job': serialize_job(job)}
    if job.status in {'succeeded', 'partial', 'failed'}:
        result['session'] = _serialize_session(job.session)
    return result


@router.post('/sessions/{session_id}/humanize')
def humanize_final(
    session_id: int,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if not session.final_content:
        raise HTTPException(status_code=409, detail='请先生成最终候选稿')

    _claim_session(db, session.id, user.id, 'humanizing')
    session = _get_owned_session(db, session_id, user)
    images = _active_images(session)
    baseline_content = assemble_final_content(
        session.final_content, images, remove_pending=True
    )
    sources = _selected_sources(db, session.id)
    writer_args = {
        'topic': session.topic,
        'title': session.final_title or session.draft_title or session.topic,
        'content': baseline_content,
        'core_points': session.core_points,
        'confirmed_brief': session.confirmed_brief,
        'writing_mode': session.writing_mode,
        'style_notes': session.style_notes,
    }
    db.commit()
    try:
        result = OpenAICompatibleWriter().humanize_article(**writer_args)
    except AIWriterError as exc:
        db.query(AIWritingSession).filter(
            AIWritingSession.id == session_id,
            AIWritingSession.author_id == user.id,
        ).update({
            AIWritingSession.status: 'final_ready',
            AIWritingSession.last_error: f'最终稿保持不变，去 AI 腔失败：{str(exc)}'[:2000],
        }, synchronize_session=False)
        db.commit()
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    revised_content, warnings = enforce_selected_citations(
        result['content'], [source['url'] for source in sources]
    )
    session.pre_humanized_title = session.final_title
    session.pre_humanized_content = baseline_content
    session.final_title = result['title']
    session.final_content = revised_content
    session.humanize_summary = result['summary']
    session.citation_warnings = json.dumps(warnings, ensure_ascii=False)
    for image in session.images:
        if image.image_type != 'cover' or image.status != 'ready':
            image.status = 'obsolete'
    db.add(AIWritingMessage(
        session_id=session.id,
        role='assistant',
        message_type='humanize',
        content=f'已完成去 AI 腔编辑：{result["summary"]}',
    ))
    db.flush()
    db.query(AIWritingSession).filter(
        AIWritingSession.id == session_id,
        AIWritingSession.author_id == user.id,
    ).update({
        AIWritingSession.status: 'final_ready',
        AIWritingSession.last_error: '',
    }, synchronize_session=False)
    db.commit()
    db.expire_all()
    session = _get_owned_session(db, session_id, user)
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/restore-humanize')
def restore_pre_humanized(
    session_id: int,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if not session.pre_humanized_content:
        raise HTTPException(status_code=409, detail='没有可恢复的润色前版本')
    session.final_title = session.pre_humanized_title or session.final_title
    session.final_content = session.pre_humanized_content
    session.pre_humanized_title = ''
    session.pre_humanized_content = ''
    session.humanize_summary = ''
    session.status = 'final_ready'
    session.last_error = ''
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/plan-images')
def plan_images(
    session_id: int,
    payload: ImagePlanRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if not session.final_content:
        raise HTTPException(status_code=409, detail='请先生成最终候选稿')

    _claim_session(db, session.id, user.id, 'planning_images')
    session = _get_owned_session(db, session_id, user)
    inline_count = min(payload.inline_image_count, settings.AI_MAX_INLINE_IMAGES)
    writer_args = {
        'topic': session.topic,
        'title': session.final_title or session.draft_title or session.topic,
        'content': session.final_content,
        'include_cover': payload.include_cover,
        'inline_image_count': inline_count,
        'image_style': payload.image_style,
    }
    db.commit()
    try:
        result = OpenAICompatibleWriter().plan_images(**writer_args)
    except AIWriterError as exc:
        db.query(AIWritingSession).filter(
            AIWritingSession.id == session_id,
            AIWritingSession.author_id == user.id,
        ).update({
            AIWritingSession.status: 'final_ready',
            AIWritingSession.last_error: f'最终稿已生成，但配图计划失败：{str(exc)}'[:2000],
        }, synchronize_session=False)
        db.commit()
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    session.final_content = result['content']
    existing = {image.slot: image for image in session.images}
    active_slots = set()
    for plan in result['images']:
        active_slots.add(plan.slot)
        image = existing.get(plan.slot)
        if image is None:
            image = AIWritingImage(session_id=session.id, slot=plan.slot)
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
        session_id=session.id,
        role='assistant',
        message_type='image_plan',
        content=f'已为最终稿规划 {len(result["images"])} 张配图。',
    ))
    db.flush()
    db.query(AIWritingSession).filter(
        AIWritingSession.id == session_id,
        AIWritingSession.author_id == user.id,
    ).update({
        AIWritingSession.status: 'final_ready',
        AIWritingSession.last_error: '',
    }, synchronize_session=False)
    db.commit()
    db.expire_all()
    session = _get_owned_session(db, session_id, user)
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/research/plan')
def plan_research(
    session_id: int,
    payload: ResearchPlanRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if payload.current_content.strip():
        session.current_content = payload.current_content.strip()
        db.commit()
    _claim_session(db, session.id, user.id, 'planning_research')
    session = _get_owned_session(db, session_id, user)
    writer_args = {
        'topic': session.topic,
        'core_points': session.core_points,
        'current_content': session.current_content,
        'focus': payload.focus,
    }
    db.commit()
    try:
        queries = OpenAICompatibleWriter().plan_research(**writer_args)
    except AIWriterError as exc:
        _fail_session(db, session_id, str(exc))
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    session.research_queries = json.dumps(queries, ensure_ascii=False)
    session.status = 'research_ready'
    session.last_error = ''
    db.add(AIWritingMessage(
        session_id=session.id,
        role='assistant',
        message_type='research_plan',
        content=f'已规划 {len(queries)} 个检索问题。只有你主动执行的搜索才会访问网络。',
    ))
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/research/search')
def search_research_sources(
    session_id: int,
    payload: ResearchSearchRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    if not settings.WEB_SEARCH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail='网络搜索未配置，请设置 WEB_SEARCH_PROVIDER、WEB_SEARCH_API_BASE 和 WEB_SEARCH_API_KEY',
        )
    session = _get_owned_session(db, session_id, user)
    _claim_session(db, session.id, user.id, 'searching')
    query = payload.query.strip()
    purpose = payload.purpose.strip()
    try:
        results = get_search_provider().search(query, settings.WEB_SEARCH_MAX_RESULTS)
    except WebSearchError as exc:
        _fail_session(db, session_id, str(exc))
        raise HTTPException(status_code=502, detail=str(exc))

    session = _get_owned_session(db, session_id, user)
    for result in results:
        source = db.query(AIResearchSource).filter(
            AIResearchSource.session_id == session.id,
            AIResearchSource.url == result.url,
        ).first()
        if source is None:
            source = AIResearchSource(
                session_id=session.id,
                url=result.url,
                selected=False,
            )
            db.add(source)
        source.query = query
        source.purpose = purpose
        source.title = result.title
        source.snippet = result.snippet
        source.source_content = result.content
        source.source_name = result.source_name
        source.published_at = result.published_at
        source.retrieved_at = datetime.utcnow()
        source.fetch_status = 'ready'
        source.content_hash = hashlib.sha256(
            f'{result.title}\n{result.url}\n{result.content}'.encode('utf-8')
        ).hexdigest()

    session.status = 'research_ready'
    session.last_error = ''
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.patch('/sessions/{session_id}/research/{source_id}')
def select_research_source(
    session_id: int,
    source_id: int,
    payload: ResearchSelectionRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    source = db.query(AIResearchSource).filter(
        AIResearchSource.id == source_id,
        AIResearchSource.session_id == session.id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail='研究资料不存在')
    source.selected = payload.selected
    session.status = 'research_ready'
    session.citation_warnings = '[]'
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/images/{image_id}/generate')
def generate_image(
    session_id: int,
    image_id: int,
    payload: ImageGenerateRequest,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    _get_owned_session(db, session_id, user)
    image = db.query(AIWritingImage).filter(
        AIWritingImage.id == image_id,
        AIWritingImage.session_id == session_id,
        AIWritingImage.status != 'obsolete',
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail='配图任务不存在')
    updated = db.query(AIWritingImage).filter(
        AIWritingImage.id == image.id,
        AIWritingImage.status != 'generating',
    ).update({
        AIWritingImage.status: 'generating',
        AIWritingImage.error: '',
        AIWritingImage.prompt: payload.prompt.strip() or image.prompt,
    }, synchronize_session=False)
    db.commit()
    if not updated:
        raise HTTPException(status_code=409, detail='该图片正在生成')
    image = db.query(AIWritingImage).filter(AIWritingImage.id == image_id).first()
    image_prompt = image.prompt
    aspect_ratio = image.aspect_ratio
    db.commit()
    try:
        image_data = OpenAICompatibleWriter().generate_image(image_prompt, aspect_ratio)
        image = db.query(AIWritingImage).filter(AIWritingImage.id == image_id).first()
        image.file_path = save_generated_image(image_data, settings.UPLOAD_DIR)
        image.status = 'ready'
        image.error = ''
        db.commit()
    except AIWriterError as exc:
        image.status = 'failed'
        image.error = str(exc)[:2000]
        db.commit()
        _raise_provider_error(exc)

    session = _get_owned_session(db, session_id, user)
    return _serialize_session(session)


@router.post('/sessions/{session_id}/apply')
def apply_final(
    session_id: int,
    request: Request,
    x_csrf_token: str = Header(default='', alias='X-CSRF-Token'),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    _require_csrf(request, x_csrf_token)
    session = _get_owned_session(db, session_id, user)
    if not session.final_content:
        raise HTTPException(status_code=409, detail='请先生成最终候选稿')
    if session.status not in {'final_ready', 'applied'}:
        raise HTTPException(status_code=409, detail='研究资料或访谈内容已更新，请重新生成最终稿')
    images = _active_images(session)
    content = assemble_final_content(session.final_content, images, remove_pending=True)
    cover = next(
        (image.file_path for image in images if image.image_type == 'cover' and image.status == 'ready'),
        '',
    )
    session.status = 'applied'
    session.current_content = content
    db.commit()
    return {
        'title': session.final_title or session.draft_title or session.topic,
        'content': content,
        'cover_image': cover,
        'missing_images': sum(1 for image in images if image.status != 'ready'),
    }
