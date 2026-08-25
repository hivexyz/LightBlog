from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, load_only, selectinload, joinedload
from sqlalchemy import or_
from app.database import get_db
from app.models import Post, Category, Tag, Setting
from app.config import settings
from app.view_counter import view_counter

router = APIRouter()

# 文章列表页只加载必要字段，避免加载 content/content_html 大字段
POST_LIST_FIELDS = [
    Post.id, Post.title, Post.slug, Post.summary,
    Post.cover_image, Post.created_at, Post.views, Post.category_id,
]

# 列表页预加载关系，避免 N+1 查询
POST_LIST_OPTIONS = [
    load_only(*POST_LIST_FIELDS),
    joinedload(Post.category),
    selectinload(Post.tags),
]


def get_site_settings(db: Session) -> dict:
    settings_map = {}
    for s in db.query(Setting).all():
        settings_map[s.key] = s.value
    return {
        'title': settings_map.get('site_title', 'LightBlog'),
        'subtitle': settings_map.get('site_subtitle', '一个轻量级的博客'),
        'description': settings_map.get('site_description', '记录生活与技术'),
        'avatar': settings_map.get('site_avatar', ''),
        'github_url': settings_map.get('github_url', ''),
    }


@router.get('/', response_class=HTMLResponse)
def index(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    per_page = settings.POSTS_PER_PAGE
    offset = (page - 1) * per_page
    posts = db.query(Post).filter(Post.status == 1) \
        .options(*POST_LIST_OPTIONS) \
        .order_by(Post.created_at.desc()) \
        .offset(offset).limit(per_page).all()
    total = db.query(Post).filter(Post.status == 1).count()
    total_pages = (total + per_page - 1) // per_page

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('index.html', {
        'request': request,
        'posts': posts,
        'page': page,
        'total_pages': total_pages,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/post/{slug}', response_class=HTMLResponse)
def post_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug, Post.status == 1).first()
    if not post:
        return HTMLResponse(status_code=404, content='<h1>404 Not Found</h1>')

    # 浏览量 +1（内存缓冲）
    view_counter.increment(post.id)

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('post.html', {
        'request': request,
        'post': post,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/category/{slug}', response_class=HTMLResponse)
def category(request: Request, slug: str, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    category = db.query(Category).filter(Category.slug == slug).first()
    if not category:
        return HTMLResponse(status_code=404, content='<h1>404 Not Found</h1>')

    per_page = settings.POSTS_PER_PAGE
    offset = (page - 1) * per_page
    posts = db.query(Post).filter(Post.status == 1, Post.category_id == category.id) \
        .options(*POST_LIST_OPTIONS) \
        .order_by(Post.created_at.desc()) \
        .offset(offset).limit(per_page).all()
    total = db.query(Post).filter(Post.status == 1, Post.category_id == category.id).count()
    total_pages = (total + per_page - 1) // per_page

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('category.html', {
        'request': request,
        'category': category,
        'posts': posts,
        'page': page,
        'total_pages': total_pages,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/tag/{slug}', response_class=HTMLResponse)
def tag(request: Request, slug: str, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.slug == slug).first()
    if not tag:
        return HTMLResponse(status_code=404, content='<h1>404 Not Found</h1>')

    per_page = settings.POSTS_PER_PAGE
    offset = (page - 1) * per_page
    posts = db.query(Post).join(Post.tags).filter(
        Post.status == 1, Tag.id == tag.id
    ).options(*POST_LIST_OPTIONS) \
     .order_by(Post.created_at.desc()).offset(offset).limit(per_page).all()
    total = db.query(Post).join(Post.tags).filter(
        Post.status == 1, Tag.id == tag.id
    ).count()
    total_pages = (total + per_page - 1) // per_page

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('tag.html', {
        'request': request,
        'tag': tag,
        'posts': posts,
        'page': page,
        'total_pages': total_pages,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/archive', response_class=HTMLResponse)
def archive(request: Request, db: Session = Depends(get_db)):
    # 只查询必要字段，避免加载 content/content_html 大字段
    posts = db.query(
        Post.id, Post.title, Post.slug, Post.created_at
    ).filter(Post.status == 1) \
     .order_by(Post.created_at.desc()).all()

    archives = {}
    for post in posts:
        year = post.created_at.year
        if year not in archives:
            archives[year] = []
        archives[year].append(post)

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('archive.html', {
        'request': request,
        'archives': archives,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/search', response_class=HTMLResponse)
def search(request: Request, q: str = '', page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    per_page = settings.POSTS_PER_PAGE
    offset = (page - 1) * per_page
    query = db.query(Post).filter(Post.status == 1)
    if q:
        query = query.filter(or_(Post.title.contains(q), Post.summary.contains(q)))
    posts = query.options(*POST_LIST_OPTIONS) \
        .order_by(Post.created_at.desc()).offset(offset).limit(per_page).all()
    total = query.count()
    total_pages = (total + per_page - 1) // per_page

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('search.html', {
        'request': request,
        'q': q,
        'posts': posts,
        'page': page,
        'total_pages': total_pages,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/about', response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    from app.utils import render_markdown
    about_setting = db.query(Setting).filter(Setting.key == 'about_content').first()
    about_html = render_markdown(about_setting.value) if about_setting else ''

    site = get_site_settings(db)
    categories = db.query(Category).all()
    tags = db.query(Tag).all()

    return request.app.state.templates.TemplateResponse('about.html', {
        'request': request,
        'about_html': about_html,
        'site': site,
        'categories': categories,
        'tags': tags,
    })


@router.get('/feed.xml')
def feed(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import Response
    posts = db.query(Post).filter(Post.status == 1) \
        .order_by(Post.created_at.desc()).limit(20).all()
    site = get_site_settings(db)
    xml = request.app.state.templates.TemplateResponse('feed.xml', {
        'request': request,
        'posts': posts,
        'site': site,
    })
    return Response(content=xml.body.decode(), media_type='application/rss+xml')
