import os
from io import BytesIO
from PIL import Image
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Post, Category, Tag, Setting
from app.config import settings
from app.auth import (
    hash_password, verify_password, create_session, get_current_user,
    get_session_id, get_csrf_nonce, _get_user_by_session,
    require_admin, is_login_locked, record_login_failure, clear_login_attempts,
    generate_csrf_token, verify_csrf_token
)
from app.utils import render_markdown, generate_slug, generate_summary, save_upload_file

router = APIRouter(prefix='/admin')


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP。

    生产环境由 nginx 反向代理注入 X-Real-IP / X-Forwarded-For；
    开发直连模式下 fallback 到 request.client.host。
    web 容器仅通过 docker compose expose 给 nginx，信任该头是合理的。
    """
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        return x_real_ip.strip()

    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # X-Forwarded-For 格式: client, proxy1, proxy2
        return x_forwarded_for.split(',')[0].strip()

    return request.client.host if request.client else 'unknown'


def make_csrf(request: Request) -> str:
    """生成绑定当前 session csrf_nonce 的 CSRF token"""
    return generate_csrf_token(get_csrf_nonce(get_session_id(request)))


def check_csrf(request: Request, token: str) -> bool:
    """校验 CSRF token 是否绑定当前 session 的 csrf_nonce"""
    return verify_csrf_token(token, get_csrf_nonce(get_session_id(request)))


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    session_id = get_session_id(request)
    user = _get_user_by_session(session_id, db) if session_id else None
    if user:
        return RedirectResponse(url='/admin/', status_code=302)
    csrf_token = generate_csrf_token(get_csrf_nonce(session_id))
    return request.app.state.templates.TemplateResponse('admin/login.html', {
        'request': request,
        'csrf_token': csrf_token,
        'error': None,
    })


@router.post('/login')
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    if not check_csrf(request, csrf_token):
        return request.app.state.templates.TemplateResponse('admin/login.html', {
            'request': request,
            'csrf_token': make_csrf(request),
            'error': 'CSRF token 无效',
        }, status_code=400)

    ip = get_client_ip(request)
    if is_login_locked(ip):
        return request.app.state.templates.TemplateResponse('admin/login.html', {
            'request': request,
            'csrf_token': make_csrf(request),
            'error': '登录失败次数过多，请 15 分钟后再试',
        }, status_code=429)

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        record_login_failure(ip)
        return request.app.state.templates.TemplateResponse('admin/login.html', {
            'request': request,
            'csrf_token': make_csrf(request),
            'error': '用户名或密码错误',
        }, status_code=401)

    clear_login_attempts(ip)
    session_id = create_session(user.id)
    response = RedirectResponse(url='/admin/', status_code=302)
    response.set_cookie(
        'session', session_id,
        httponly=True, secure=settings.COOKIE_SECURE, samesite='lax',
        max_age=7 * 24 * 3600
    )
    return response


@router.get('/logout')
def logout():
    response = RedirectResponse(url='/admin/login', status_code=302)
    response.delete_cookie('session')
    return response


@router.get('/', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    total_posts = db.query(Post).count()
    published_posts = db.query(Post).filter(Post.status == 1).count()
    total_views = db.query(Post.views).all()
    total_views = sum(v[0] for v in total_views) if total_views else 0
    total_categories = db.query(Category).count()
    total_tags = db.query(Tag).count()
    recent_posts = db.query(Post).order_by(Post.created_at.desc()).limit(5).all()

    return request.app.state.templates.TemplateResponse('admin/dashboard.html', {
        'request': request,
        'user': user,
        'total_posts': total_posts,
        'published_posts': published_posts,
        'total_views': total_views,
        'total_categories': total_categories,
        'total_tags': total_tags,
        'recent_posts': recent_posts,
    })


@router.get('/posts', response_class=HTMLResponse)
def posts_list(request: Request, page: int = 1, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    per_page = settings.POSTS_PER_PAGE
    offset = (page - 1) * per_page
    posts = db.query(Post).order_by(Post.created_at.desc()).offset(offset).limit(per_page).all()
    total = db.query(Post).count()
    total_pages = (total + per_page - 1) // per_page

    return request.app.state.templates.TemplateResponse('admin/posts.html', {
        'request': request,
        'user': user,
        'posts': posts,
        'page': page,
        'total_pages': total_pages,
        'csrf_token': make_csrf(request),
    })


@router.get('/post/new', response_class=HTMLResponse)
def new_post_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    categories = db.query(Category).all()
    tags = db.query(Tag).all()
    return request.app.state.templates.TemplateResponse('admin/post_form.html', {
        'request': request,
        'user': user,
        'post': None,
        'categories': categories,
        'tags': tags,
        'csrf_token': make_csrf(request),
    })


def _make_unique_slug(db: Session, title: str, exclude_id: int = None) -> str:
    """生成唯一 slug，排除指定文章 ID（用于编辑场景）"""
    slug = generate_slug(title)
    original_slug = slug
    counter = 1
    query = db.query(Post).filter(Post.slug == slug)
    if exclude_id:
        query = query.filter(Post.id != exclude_id)
    while query.first():
        slug = f'{original_slug}-{counter}'
        counter += 1
        query = db.query(Post).filter(Post.slug == slug)
        if exclude_id:
            query = query.filter(Post.id != exclude_id)
    return slug


@router.post('/post/new')
def create_post(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    category_id: int = Form(None),
    tag_ids: list[int] = Form(None),
    status: int = Form(1),
    cover_image: str = Form(''),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')

    slug = _make_unique_slug(db, title)
    content_html = render_markdown(content)
    summary = generate_summary(content)

    post = Post(
        title=title,
        slug=slug,
        content=content,
        content_html=content_html,
        summary=summary,
        cover_image=cover_image,
        status=status,
        category_id=category_id,
        author_id=user.id
    )
    if tag_ids:
        post.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()

    db.add(post)
    db.commit()
    return RedirectResponse(url='/admin/posts', status_code=302)


@router.get('/post/{post_id}/edit', response_class=HTMLResponse)
def edit_post_page(request: Request, post_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()
    return request.app.state.templates.TemplateResponse('admin/post_form.html', {
        'request': request,
        'user': user,
        'post': post,
        'categories': categories,
        'tags': tags,
        'csrf_token': make_csrf(request),
    })


@router.post('/post/{post_id}/edit')
def update_post(
    request: Request,
    post_id: int,
    title: str = Form(...),
    content: str = Form(...),
    category_id: int = Form(None),
    tag_ids: list[int] = Form(None),
    status: int = Form(1),
    cover_image: str = Form(''),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')

    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404)

    post.title = title
    post.content = content
    post.category_id = category_id
    post.status = status
    post.cover_image = cover_image
    # 编辑时 slug 去重，排除当前文章
    post.slug = _make_unique_slug(db, title, exclude_id=post_id)
    post.content_html = render_markdown(content)
    post.summary = generate_summary(content)

    if tag_ids:
        post.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    else:
        post.tags = []

    db.commit()
    return RedirectResponse(url='/admin/posts', status_code=302)


@router.post('/post/{post_id}/delete')
def delete_post(
    request: Request,
    post_id: int,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        db.delete(post)
        db.commit()
    return RedirectResponse(url='/admin/posts', status_code=302)


@router.get('/categories', response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    categories = db.query(Category).all()
    return request.app.state.templates.TemplateResponse('admin/categories.html', {
        'request': request,
        'user': user,
        'categories': categories,
        'csrf_token': make_csrf(request),
    })


@router.post('/categories')
def create_category(
    request: Request,
    name: str = Form(...),
    description: str = Form(''),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')
    slug = generate_slug(name)
    if not db.query(Category).filter(Category.slug == slug).first():
        category = Category(name=name, slug=slug, description=description)
        db.add(category)
        db.commit()
    return RedirectResponse(url='/admin/categories', status_code=302)


@router.post('/category/{category_id}/delete')
def delete_category(
    request: Request,
    category_id: int,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')
    category = db.query(Category).filter(Category.id == category_id).first()
    if category:
        db.query(Post).filter(Post.category_id == category_id).update({Post.category_id: None})
        db.delete(category)
        db.commit()
    return RedirectResponse(url='/admin/categories', status_code=302)


@router.get('/tags', response_class=HTMLResponse)
def tags_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    tags = db.query(Tag).all()
    return request.app.state.templates.TemplateResponse('admin/tags.html', {
        'request': request,
        'user': user,
        'tags': tags,
        'csrf_token': make_csrf(request),
    })


@router.post('/tags')
def create_tag(
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')
    slug = generate_slug(name)
    if not db.query(Tag).filter(Tag.slug == slug).first():
        tag = Tag(name=name, slug=slug)
        db.add(tag)
        db.commit()
    return RedirectResponse(url='/admin/tags', status_code=302)


@router.post('/tag/{tag_id}/delete')
def delete_tag(
    request: Request,
    tag_id: int,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if tag:
        db.delete(tag)
        db.commit()
    return RedirectResponse(url='/admin/tags', status_code=302)


@router.get('/settings', response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    settings_map = {}
    for s in db.query(Setting).all():
        settings_map[s.key] = s.value
    return request.app.state.templates.TemplateResponse('admin/settings.html', {
        'request': request,
        'user': user,
        'site_settings': settings_map,
        'csrf_token': make_csrf(request),
    })


@router.post('/settings')
def update_settings(
    request: Request,
    site_title: str = Form(''),
    site_subtitle: str = Form(''),
    site_description: str = Form(''),
    site_avatar: str = Form(''),
    github_url: str = Form(''),
    about_content: str = Form(''),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')

    values = {
        'site_title': site_title,
        'site_subtitle': site_subtitle,
        'site_description': site_description,
        'site_avatar': site_avatar,
        'github_url': github_url,
        'about_content': about_content,
    }
    for key, value in values.items():
        setting = db.query(Setting).filter(Setting.key == key).first()
        if setting:
            setting.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return RedirectResponse(url='/admin/settings', status_code=302)


@router.post('/upload')
def upload_image(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_admin)
):
    if not check_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail='CSRF token 无效')

    # 校验后缀
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}')

    # 校验大小
    content = file.file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail='文件大小超过 5MB 限制')

    # 校验真实图片类型（Pillow Image.verify）
    try:
        file.file.seek(0)
        img = Image.open(file.file)
        img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail='文件不是有效的图片')

    file.file.seek(0)
    url = save_upload_file(file, settings.UPLOAD_DIR)
    return JSONResponse({'url': url})
