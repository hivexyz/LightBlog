import re
import uuid
import os
from datetime import datetime
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.toc import TocExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from pymdownx.arithmatex import ArithmatexExtension
import bleach
from bleach.css_sanitizer import CSSSanitizer

# bleach 白名单
ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li',
    'ol', 'p', 'pre', 'strong', 'ul', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'br', 'hr', 'div', 'span', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'figure', 'figcaption'
]


def allow_img_src(tag, name, value):
    """img src 仅允许 http/https 协议及本站 /uploads/、/static/ 路径"""
    if name == 'src':
        return value.startswith(('http://', 'https://', '/uploads/', '/static/'))
    return True


def img_attr_filter(tag, attr, value):
    """img 标签属性过滤：src 走 allow_img_src，其余允许 alt/title/width/height"""
    if attr == 'src':
        return allow_img_src(tag, attr, value)
    return attr in ('alt', 'title', 'width', 'height')


ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'rel'],
    'img': img_attr_filter,
    'code': ['class'],
    'pre': ['class'],
    'span': ['class'],
    'div': ['class'],
    'table': ['class'],
}


def render_markdown(text: str) -> str:
    """将 Markdown 渲染为 HTML 并做 XSS 清洗。

    数学公式：使用 pymdownx.arithmatex (generic 模式)，
    行内 $...$ 输出 <span class="arithmatex">\\(...\\)</span>，
    块级 $$...$$ 输出 <div class="arithmatex">\\[...\\]</div>，
    由前端 KaTeX auto-render 渲染。
    """
    extensions = [
        CodeHiliteExtension(guess_lang=False, linenums=False, css_class='highlight'),
        TocExtension(permalink=True),
        FencedCodeExtension(),
        TableExtension(),
        'extra',
        ArithmatexExtension(generic=True),
    ]
    md = markdown.Markdown(extensions=extensions)
    html = md.convert(text)
    # bleach 清洗
    html = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=CSSSanitizer(),
        strip=True
    )
    # 链接添加 rel="nofollow noopener noreferrer"
    html = bleach.linkify(html, callbacks=[_set_link_rel])
    return html


def _set_link_rel(attrs, new=False):
    attrs[(None, 'rel')] = 'nofollow noopener noreferrer'
    return attrs


def generate_slug(text: str) -> str:
    """生成 URL 友好的 slug"""
    text = text.strip().lower()
    text = re.sub(r'[^\w\u4e00-\u9fa5-]', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    return text or 'post'


def generate_summary(content: str, length: int = 200) -> str:
    """从 Markdown 内容生成纯文本摘要"""
    text = re.sub(r'[#*`>\-!~\[\]()]', '', content)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:length] + '...' if len(text) > length else text


def save_upload_file(file, upload_dir: str) -> str:
    """保存上传文件，返回相对 URL"""
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    filename = f'{uuid.uuid4().hex}.{ext}'
    date_path = datetime.now().strftime('%Y/%m')
    save_dir = os.path.join(upload_dir, date_path)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    with open(save_path, 'wb') as f:
        f.write(file.file.read())
    return f'/uploads/{date_path}/{filename}'
