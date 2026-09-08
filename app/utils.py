import re
import uuid
import os
from datetime import datetime
from io import BytesIO
from urllib.parse import unquote, urlparse
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.toc import TocExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from pymdownx.arithmatex import ArithmatexExtension
import bleach
from bleach.css_sanitizer import CSSSanitizer
from PIL import Image, ImageDraw, ImageFont

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
        TocExtension(permalink=False),
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
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', content)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.S)
    text = re.sub(r'\$[^$\n]+\$', '', text)
    text = re.sub(r'[#*`>\-!~\[\]()]', '', text)
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


def safe_download_filename(name: str, fallback: str = 'download') -> str:
    """生成适合下载和 ZIP 内路径使用的文件名，保留中文。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', '-', name).strip(' .')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:90] or fallback


EXPORT_IMAGE_TEMPLATES = [
    {'id': 'paper', 'name': '暖纸书页'},
    {'id': 'clean', 'name': '清爽白底'},
    {'id': 'dark', 'name': '深色卡片'},
    {'id': 'mint', 'name': '墨绿笔记'},
]


EXPORT_IMAGE_FONTS = [
    {'id': 'noto-sans-cjk', 'name': '思源黑体'},
    {'id': 'noto-serif-cjk', 'name': '思源宋体'},
    {'id': 'wenquanyi-microhei', 'name': '文泉驿微米黑'},
    {'id': 'wenquanyi-zenhei', 'name': '文泉驿正黑'},
    {'id': 'arphic-uming', 'name': '文鼎明体'},
    {'id': 'arphic-ukai', 'name': '文鼎楷体'},
]


_EXPORT_IMAGE_FONT_CONFIGS = {
    'noto-sans-cjk': {
        'regular': [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            ('/System/Library/Fonts/Hiragino Sans GB.ttc', 0),
            ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ],
        'bold': [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
            ('/System/Library/Fonts/Hiragino Sans GB.ttc', 2),
            ('/System/Library/Fonts/STHeiti Medium.ttc', 1),
        ],
    },
    'noto-serif-cjk': {
        'regular': [
            '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 6),
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 4),
        ],
        'bold': [
            '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 1),
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 0),
        ],
    },
    'wenquanyi-microhei': {
        'regular': [
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ],
        'bold': [
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            ('/System/Library/Fonts/STHeiti Medium.ttc', 1),
        ],
    },
    'wenquanyi-zenhei': {
        'regular': [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ],
        'bold': [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            ('/System/Library/Fonts/STHeiti Medium.ttc', 1),
        ],
    },
    'arphic-uming': {
        'regular': [
            '/usr/share/fonts/truetype/arphic/uming.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 4),
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 6),
        ],
        'bold': [
            '/usr/share/fonts/truetype/arphic/uming.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 1),
        ],
    },
    'arphic-ukai': {
        'regular': [
            '/usr/share/fonts/truetype/arphic/ukai.ttc',
            '/System/Library/Fonts/Supplemental/Kaiti.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 3),
        ],
        'bold': [
            '/usr/share/fonts/truetype/arphic/ukai.ttc',
            '/System/Library/Fonts/Supplemental/Kaiti.ttc',
            ('/System/Library/Fonts/Supplemental/Songti.ttc', 0),
        ],
    },
}


_EXPORT_IMAGE_TEMPLATE_CONFIGS = {
    'paper': {
        'font': 'serif',
        'bg_top': '#f3f7f4',
        'bg_bottom': '#fff8ef',
        'paper': '#fffefb',
        'ink': '#25302b',
        'text': '#2f3430',
        'muted': '#69766f',
        'subtle': '#9aa49e',
        'border': '#e7ddd1',
        'primary': '#2f6f68',
        'accent': '#c47a35',
        'quote_bg': '#f6faf7',
        'code_bg': '#f3f0ea',
        'table_header_bg': '#eef5f2',
        'header_bg': '#edf5f1',
        'header_wave': '#fff2df',
        'badge_bg': '#edf5f2',
        'badge_border': '#d7e8e3',
        'rule': '#efe0cf',
    },
    'clean': {
        'font': 'sans',
        'bg_top': '#eef4ff',
        'bg_bottom': '#f8fbff',
        'paper': '#ffffff',
        'ink': '#172033',
        'text': '#344054',
        'muted': '#667085',
        'subtle': '#98a2b3',
        'border': '#dbe4f0',
        'primary': '#1f6feb',
        'accent': '#7c3aed',
        'quote_bg': '#f8fafc',
        'code_bg': '#f4f7fb',
        'table_header_bg': '#eef4ff',
        'header_bg': '#eff6ff',
        'header_wave': '#f7f3ff',
        'badge_bg': '#eef4ff',
        'badge_border': '#c7d7fe',
        'rule': '#e8eef7',
    },
    'dark': {
        'font': 'sans',
        'bg_top': '#101827',
        'bg_bottom': '#293243',
        'paper': '#151f2e',
        'ink': '#f8fafc',
        'text': '#dbe4ee',
        'muted': '#b5c0cc',
        'subtle': '#7e8b99',
        'border': '#334155',
        'primary': '#5eead4',
        'accent': '#fbbf24',
        'quote_bg': '#1d2b3c',
        'code_bg': '#0f172a',
        'table_header_bg': '#1f3347',
        'header_bg': '#182638',
        'header_wave': '#26364a',
        'badge_bg': '#102a33',
        'badge_border': '#245e63',
        'rule': '#243244',
    },
    'mint': {
        'font': 'serif',
        'bg_top': '#e7f6ef',
        'bg_bottom': '#fbf7ec',
        'paper': '#fffffb',
        'ink': '#1e342d',
        'text': '#30443d',
        'muted': '#64756f',
        'subtle': '#96a49f',
        'border': '#d9eadf',
        'primary': '#0f766e',
        'accent': '#d88a2d',
        'quote_bg': '#eef8f2',
        'code_bg': '#f1f4ed',
        'table_header_bg': '#e7f6ef',
        'header_bg': '#e2f4eb',
        'header_wave': '#fff0dc',
        'badge_bg': '#e8f7ef',
        'badge_border': '#c7e6d6',
        'rule': '#e7decf',
    },
}


def get_export_image_templates() -> list[dict[str, str]]:
    return list(EXPORT_IMAGE_TEMPLATES)


def get_export_image_fonts() -> list[dict[str, str]]:
    return list(EXPORT_IMAGE_FONTS)


def normalize_export_image_template(template: str | None) -> str:
    return template if template in _EXPORT_IMAGE_TEMPLATE_CONFIGS else 'paper'


def normalize_export_image_font(font: str | None) -> str:
    return font if font in _EXPORT_IMAGE_FONT_CONFIGS else 'noto-sans-cjk'


def _get_export_image_template(template: str | None) -> dict:
    return _EXPORT_IMAGE_TEMPLATE_CONFIGS[normalize_export_image_template(template)]


def export_markdown_chapter_images(
    title: str,
    content: str,
    created_at=None,
    image_roots: dict[str, str] | None = None,
    template: str = 'paper',
    font: str = 'noto-sans-cjk',
) -> list[tuple[str, bytes]]:
    """将 Markdown 按 # / ## 章节拆分并导出为 PNG 长图。"""
    chapters = _split_markdown_chapters(content)
    total = len(chapters)
    images = []
    for index, chapter in enumerate(chapters, start=1):
        renderer = _MarkdownImageRenderer(
            image_roots=image_roots or {},
            template=_get_export_image_template(template),
            font=normalize_export_image_font(font),
        )
        png = renderer.render(
            article_title=title,
            chapter_title=chapter['title'],
            chapter_index=index,
            chapter_total=total,
            created_at=created_at,
            markdown_text=chapter['content'],
        )
        filename = f'{index:02d}-{safe_download_filename(chapter["title"], "chapter")}.png'
        images.append((filename, png))
    return images


def render_markdown_chapter_preview_image(
    title: str,
    content: str,
    created_at=None,
    image_roots: dict[str, str] | None = None,
    template: str = 'paper',
    font: str = 'noto-sans-cjk',
) -> bytes:
    """渲染第一章预览 PNG，供后台模板选择弹窗使用。"""
    chapters = _split_markdown_chapters(content)
    chapter = chapters[0] if chapters else {'title': '全文', 'content': content or ''}
    renderer = _MarkdownImageRenderer(
        image_roots=image_roots or {},
        template=_get_export_image_template(template),
        font=normalize_export_image_font(font),
    )
    return renderer.render(
        article_title=title,
        chapter_title=chapter['title'],
        chapter_index=1,
        chapter_total=max(len(chapters), 1),
        created_at=created_at,
        markdown_text=chapter['content'],
    )


def _split_markdown_chapters(content: str) -> list[dict[str, str]]:
    """以一级、二级标题作为章节边界；无标题时导出全文。"""
    chapters = []
    current_title = '开篇'
    current_lines = []
    in_fence = False
    fence_marker = ''

    for line in content.splitlines():
        stripped = line.strip()
        fence = re.match(r'^(```+|~~~+)', stripped)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[:3]
            elif stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ''
            current_lines.append(line)
            continue

        match = None if in_fence else re.match(r'^(#{1,2})\s+(.+?)\s*#*\s*$', line)
        if match:
            if any(item.strip() for item in current_lines):
                chapters.append({
                    'title': current_title,
                    'content': '\n'.join(current_lines).strip(),
                })
            current_title = _clean_inline_markdown(match.group(2)) or '未命名章节'
            current_lines = [line]
        else:
            current_lines.append(line)

    if any(item.strip() for item in current_lines):
        chapters.append({
            'title': current_title,
            'content': '\n'.join(current_lines).strip(),
        })

    if not chapters:
        chapters.append({'title': '全文', 'content': content or ''})
    return chapters


class _MarkdownImageRenderer:
    width = 1242
    margin_x = 104
    margin_y = 88
    content_width = width - margin_x * 2

    def __init__(self, image_roots: dict[str, str], template: dict, font: str):
        self.image_roots = image_roots
        self.template = template
        self.bg_top = template['bg_top']
        self.bg_bottom = template['bg_bottom']
        self.paper = template['paper']
        self.ink = template['ink']
        self.text = template['text']
        self.muted = template['muted']
        self.subtle = template['subtle']
        self.border = template['border']
        self.primary = template['primary']
        self.accent = template['accent']
        self.quote_bg = template['quote_bg']
        self.code_bg = template['code_bg']
        self.table_header_bg = template['table_header_bg']
        serif = template.get('font') == 'serif'
        self.fonts = {
            'title': _load_font(54, bold=True, serif=serif, font_id=font),
            'eyebrow': _load_font(22, serif=serif, font_id=font),
            'meta': _load_font(21, serif=serif, font_id=font),
            'h1': _load_font(39, bold=True, serif=serif, font_id=font),
            'h2': _load_font(34, bold=True, serif=serif, font_id=font),
            'h3': _load_font(29, bold=True, serif=serif, font_id=font),
            'body': _load_font(26, serif=serif, font_id=font),
            'bold': _load_font(26, bold=True, serif=serif, font_id=font),
            'small': _load_font(21, font_id=font),
            'code': _load_font(21, mono=True),
            'math': _load_font(26, font_id=font),
            'math_small': _load_font(18, font_id=font),
        }

    def render(
        self,
        article_title: str,
        chapter_title: str,
        chapter_index: int,
        chapter_total: int,
        created_at,
        markdown_text: str,
    ) -> bytes:
        blocks = _parse_markdown_blocks(markdown_text)
        ops, height = self._layout(
            blocks=blocks,
            article_title=article_title,
            chapter_title=chapter_title,
            chapter_index=chapter_index,
            chapter_total=chapter_total,
            created_at=created_at,
        )
        image = self._make_canvas(height)
        draw = ImageDraw.Draw(image)
        for op in ops:
            if op['type'] == 'text':
                draw.text(op['xy'], op['text'], font=op['font'], fill=op['fill'])
            elif op['type'] == 'line':
                draw.line(op['xy'], fill=op['fill'], width=op.get('width', 1))
            elif op['type'] == 'rect':
                draw.rounded_rectangle(op['xy'], radius=op.get('radius', 0), fill=op['fill'], outline=op.get('outline'))
            elif op['type'] == 'image':
                image.paste(op['image'], op['xy'])

        output = BytesIO()
        image.save(output, format='PNG', optimize=True)
        return output.getvalue()

    def _make_canvas(self, height: int) -> Image.Image:
        image = Image.new('RGB', (self.width, height), self.bg_bottom)
        draw = ImageDraw.Draw(image)

        for y in range(height):
            ratio = y / max(height - 1, 1)
            color = _mix_color(self.bg_top, self.bg_bottom, ratio)
            draw.line((0, y, self.width, y), fill=color)

        for y in range(300, height, 44):
            draw.line((58, y, self.width - 58, y), fill='#f1e8dd', width=1)
        draw.rounded_rectangle(
            (48, 48, self.width - 48, height - 48),
            radius=8,
            fill=self.paper,
            outline=self.border,
        )
        draw.rectangle((48, 48, self.width - 48, 216), fill=self.template['header_bg'])
        draw.polygon(
            [(48, 170), (self.width - 48, 112), (self.width - 48, 216), (48, 252)],
            fill=self.template['header_wave'],
        )
        draw.rectangle((48, 48, self.width - 48, 64), fill=self.primary)
        draw.rectangle((48, 64, 168, 76), fill=self.accent)
        draw.line((48, 252, self.width - 48, 252), fill=self.template['rule'], width=1)
        return image

    def _layout(self, blocks, article_title, chapter_title, chapter_index, chapter_total, created_at):
        measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        ops = []
        x = self.margin_x
        y = self.margin_y
        header_title = article_title if chapter_title in ('开篇', '全文') else chapter_title

        ops.append({
            'type': 'rect',
            'xy': (x, y, x + 154, y + 34),
            'fill': self.template['badge_bg'],
            'outline': self.template['badge_border'],
            'radius': 8,
        })
        ops.append({
            'type': 'text',
            'xy': (x + 20, y + 4),
            'text': f'{chapter_index:02d} / {chapter_total:02d}',
            'font': self.fonts['meta'],
            'fill': self.primary,
        })
        y += 58

        if chapter_title not in ('开篇', '全文'):
            y = self._add_wrapped_text(ops, measure, article_title, self.fonts['eyebrow'], x, y, self.content_width, self.muted, 6)
            y += 10
        y = self._add_wrapped_text(ops, measure, header_title, self.fonts['title'], x, y, self.content_width, self.ink, 12)
        meta_parts = []
        if created_at:
            meta_parts.append(created_at.strftime('%Y-%m-%d'))
        meta_parts.append('Markdown 长图')
        y = self._add_wrapped_text(ops, measure, ' · '.join(meta_parts), self.fonts['meta'], x, y + 12, self.content_width, self.muted, 6)
        y += 28
        ops.append({'type': 'line', 'xy': (x, y, x + 168, y), 'fill': self.accent, 'width': 4})
        ops.append({'type': 'line', 'xy': (x + 188, y, x + self.content_width, y), 'fill': self.border, 'width': 2})
        y += 44

        body_blocks = blocks
        if chapter_title not in ('开篇', '全文') and blocks:
            first = blocks[0]
            if first.get('kind') == 'heading' and first.get('level') <= 2 and first.get('text') == chapter_title:
                body_blocks = blocks[1:]

        for block in body_blocks:
            y = self._layout_block(ops, measure, block, x, y)

        y += 10
        ops.append({'type': 'line', 'xy': (x, y, x + self.content_width, y), 'fill': self.template['rule'], 'width': 1})
        y += 22
        ops.append({
            'type': 'text',
            'xy': (x, y),
            'text': article_title,
            'font': self.fonts['small'],
            'fill': self.subtle,
        })

        height = max(y + self.margin_y, 520)
        return ops, height

    def _layout_block(self, ops, draw, block, x, y):
        kind = block['kind']
        if kind == 'heading':
            level = block['level']
            font = self.fonts['h1'] if level == 1 else self.fonts['h2'] if level == 2 else self.fonts['h3']
            if y > self.margin_y + 140:
                y += 18
            if level <= 2:
                ops.append({'type': 'line', 'xy': (x, y + 8, x + 6, y + 46), 'fill': self.accent, 'width': 6})
                text_x = x + 22
            else:
                text_x = x
            y = self._add_wrapped_text(ops, draw, block['text'], font, text_x, y, self.content_width - (text_x - x), self.ink, 8)
            return y + 18

        if kind == 'paragraph':
            if block.get('segments'):
                y = self._add_inline_segments(ops, draw, block['segments'], x, y, self.content_width, self.text, 12)
                return y + 20
            y = self._add_wrapped_text(ops, draw, block['text'], self.fonts['body'], x, y, self.content_width, self.text, 12)
            return y + 20

        if kind == 'list':
            for item in block['items']:
                marker = f'{item["number"]}.' if item.get('number') else '•'
                marker_width = 46
                lines = _wrap_text(draw, item['text'], self.fonts['body'], self.content_width - marker_width)
                line_height = _line_height(self.fonts['body']) + 12
                ops.append({'type': 'text', 'xy': (x + 4, y), 'text': marker, 'font': self.fonts['body'], 'fill': self.accent})
                for line_index, line in enumerate(lines):
                    ops.append({
                        'type': 'text',
                        'xy': (x + marker_width, y + line_index * line_height),
                        'text': line,
                        'font': self.fonts['body'],
                        'fill': self.text,
                    })
                y += max(1, len(lines)) * line_height + 8
            return y + 14

        if kind == 'quote':
            quote_x = x + 28
            quote_width = self.content_width - 56
            start_y = y
            y += 22
            text_start = len(ops)
            y = self._add_wrapped_text(ops, draw, block['text'], self.fonts['body'], quote_x + 26, y, quote_width - 46, self.muted, 12)
            y += 22
            quote_ops = [
                {'type': 'rect', 'xy': (x, start_y, x + self.content_width, y), 'fill': self.quote_bg, 'outline': self.border, 'radius': 8},
                {'type': 'rect', 'xy': (quote_x, start_y + 22, quote_x + 7, y - 22), 'fill': self.primary, 'radius': 3},
            ]
            ops[text_start:text_start] = quote_ops
            return y + 22

        if kind == 'code':
            return self._layout_code(ops, draw, block.get('text', ''), x, y)

        if kind == 'math':
            return self._layout_math(ops, draw, block.get('text', ''), x, y)

        if kind == 'table':
            return self._layout_table(ops, draw, block['rows'], x, y)

        if kind == 'image':
            return self._layout_image(ops, draw, block, x, y)

        if kind == 'hr':
            y += 10
            ops.append({'type': 'line', 'xy': (x, y, x + self.content_width, y), 'fill': self.border, 'width': 2})
            return y + 30

        return y

    def _layout_code(self, ops, draw, text, x, y):
        pad = 24
        box = {'type': 'rect', 'xy': [x, y, x + self.content_width, y], 'fill': self.code_bg, 'outline': self.border, 'radius': 8}
        ops.append(box)
        y += pad
        for raw_line in text.splitlines() or ['']:
            lines = _wrap_text(draw, raw_line.replace('\t', '    '), self.fonts['code'], self.content_width - pad * 2, preserve_spaces=True)
            line_height = _line_height(self.fonts['code']) + 8
            for line in lines:
                ops.append({'type': 'text', 'xy': (x + pad, y), 'text': line, 'font': self.fonts['code'], 'fill': self.text})
                y += line_height
        y += pad
        box['xy'][3] = y
        return y + 24

    def _layout_math(self, ops, draw, text, x, y):
        pad_x = 28
        pad_y = 24
        box = {
            'type': 'rect',
            'xy': [x, y, x + self.content_width, y],
            'fill': self.quote_bg,
            'outline': self.border,
            'radius': 8,
        }
        ops.append(box)
        y += pad_y
        ops.append({
            'type': 'text',
            'xy': (x + pad_x, y),
            'text': '公式',
            'font': self.fonts['small'],
            'fill': self.accent,
        })
        y += _line_height(self.fonts['small']) + 14

        for raw_line in text.splitlines() or ['']:
            tokens = _format_latex_tokens(raw_line.strip())
            if not tokens:
                continue
            y = self._add_math_line(
                ops,
                draw,
                tokens,
                x + pad_x,
                y,
                self.content_width - pad_x * 2,
            )
            y += 12

        y += pad_y
        box['xy'][3] = y
        return y + 24

    def _add_math_line(self, ops, draw, tokens, x, y, max_width):
        normal_font = self.fonts['math']
        small_font = self.fonts['math_small']
        return _append_wrapped_math_tokens(ops, draw, tokens, x, y, max_width, normal_font, small_font, self.ink)

    def _layout_table(self, ops, draw, rows, x, y):
        if not rows:
            return y

        column_count = max(len(row) for row in rows)
        if column_count <= 0:
            return y

        cell_pad_x = 16
        cell_pad_y = 12
        col_width = self.content_width // column_count
        row_layouts = []
        for row in rows:
            cell_lines = []
            row_height = 0
            for index in range(column_count):
                cell = row[index] if index < len(row) else ''
                lines = _wrap_text(draw, cell, self.fonts['small'], col_width - cell_pad_x * 2)
                cell_lines.append(lines)
                row_height = max(row_height, len(lines) * (_line_height(self.fonts['small']) + 7) + cell_pad_y * 2)
            row_layouts.append((cell_lines, row_height))

        start_y = y
        for row_index, (cell_lines, row_height) in enumerate(row_layouts):
            fill = self.table_header_bg if row_index == 0 else self.paper
            ops.append({
                'type': 'rect',
                'xy': (x, y, x + col_width * column_count, y + row_height),
                'fill': fill,
                'outline': self.border,
                'radius': 0,
            })
            for col_index, lines in enumerate(cell_lines):
                cell_x = x + col_index * col_width
                if col_index > 0:
                    ops.append({'type': 'line', 'xy': (cell_x, y, cell_x, y + row_height), 'fill': self.border, 'width': 1})
                line_y = y + cell_pad_y
                for line in lines:
                    ops.append({
                        'type': 'text',
                        'xy': (cell_x + cell_pad_x, line_y),
                        'text': line,
                        'font': self.fonts['small'],
                        'fill': self.ink if row_index == 0 else self.text,
                    })
                    line_y += _line_height(self.fonts['small']) + 7
            y += row_height

        ops.append({'type': 'rect', 'xy': (x, start_y, x + col_width * column_count, y), 'fill': None, 'outline': self.border, 'radius': 8})
        return y + 24

    def _layout_image(self, ops, draw, block, x, y):
        resolved = self._open_local_image(block['src'])
        if not resolved:
            text = f'[图片无法嵌入] {block["alt"] or block["src"]}'
            y = self._add_wrapped_text(ops, draw, text, self.fonts['small'], x, y, self.content_width, self.subtle, 6)
            return y + 16

        image = resolved.convert('RGB')
        max_width = self.content_width
        if image.width > max_width:
            ratio = max_width / image.width
            image = image.resize((max_width, int(image.height * ratio)), Image.Resampling.LANCZOS)
        image_x = x + (self.content_width - image.width) // 2
        ops.append({'type': 'image', 'xy': (image_x, y), 'image': image})
        y += image.height + 10
        if block['alt']:
            y = self._add_wrapped_text(ops, draw, block['alt'], self.fonts['small'], x, y, self.content_width, self.subtle, 5)
        return y + 18

    def _open_local_image(self, src: str):
        parsed = urlparse(src)
        if parsed.scheme or parsed.netloc:
            return None

        path = unquote(parsed.path or src)
        for prefix, root in self.image_roots.items():
            if path.startswith(prefix):
                relative = path[len(prefix):].lstrip('/')
                candidate = os.path.abspath(os.path.join(root, relative))
                root_abs = os.path.abspath(root)
                if candidate.startswith(root_abs + os.sep) and os.path.exists(candidate):
                    try:
                        return Image.open(candidate)
                    except Exception:
                        return None
        return None

    def _add_wrapped_text(self, ops, draw, text, font, x, y, max_width, fill, line_gap):
        lines = _wrap_text(draw, text, font, max_width)
        line_height = _line_height(font) + line_gap
        for line in lines:
            ops.append({'type': 'text', 'xy': (x, y), 'text': line, 'font': font, 'fill': fill})
            y += line_height
        return y

    def _add_inline_segments(self, ops, draw, segments, x, y, max_width, fill, line_gap):
        normal_font = self.fonts['body']
        math_font = self.fonts['math']
        small_font = self.fonts['math_small']
        atoms = list(_iter_inline_atoms(segments))
        return _append_wrapped_math_tokens(
            ops,
            draw,
            atoms,
            x,
            y,
            max_width,
            math_font,
            small_font,
            fill,
            plain_font=normal_font,
            line_gap=line_gap,
        )


def _parse_markdown_blocks(content: str) -> list[dict]:
    blocks = []
    lines = content.splitlines()
    paragraph = []
    i = 0

    def flush_paragraph():
        if paragraph:
            raw_text = ' '.join(line.strip() for line in paragraph)
            text = _clean_inline_markdown(raw_text)
            if text:
                blocks.append({'kind': 'paragraph', 'text': text, 'segments': _parse_inline_segments(raw_text)})
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        fence = re.match(r'^(```+|~~~+)', stripped)
        if fence:
            flush_paragraph()
            marker = fence.group(1)
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith(marker[:3]):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            blocks.append({'kind': 'code', 'text': '\n'.join(code_lines)})
            continue

        if stripped.startswith('$$'):
            flush_paragraph()
            math_lines = []
            opening_text = stripped[2:].strip()
            if opening_text.endswith('$$') and len(opening_text) >= 2:
                math_lines.append(opening_text[:-2].strip())
                i += 1
            else:
                if opening_text:
                    math_lines.append(opening_text)
                i += 1
                while i < len(lines):
                    candidate = lines[i].rstrip()
                    if candidate.strip().endswith('$$'):
                        closing_text = re.sub(r'\s*\$\$\s*$', '', candidate).strip()
                        if closing_text:
                            math_lines.append(closing_text)
                        i += 1
                        break
                    math_lines.append(lines[i])
                    i += 1
            blocks.append({'kind': 'math', 'text': '\n'.join(math_lines).strip()})
            continue

        heading = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', stripped)
        if heading:
            flush_paragraph()
            blocks.append({
                'kind': 'heading',
                'level': len(heading.group(1)),
                'text': _clean_inline_markdown(heading.group(2)),
            })
            i += 1
            continue

        image = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', stripped)
        if image:
            flush_paragraph()
            blocks.append({'kind': 'image', 'alt': image.group(1).strip(), 'src': image.group(2).strip()})
            i += 1
            continue

        if re.match(r'^([-*_])\s*(\1\s*){2,}$', stripped):
            flush_paragraph()
            blocks.append({'kind': 'hr'})
            i += 1
            continue

        if stripped.startswith('>'):
            flush_paragraph()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(lines[i].strip().lstrip('>').strip())
                i += 1
            blocks.append({'kind': 'quote', 'text': _clean_inline_markdown(' '.join(quote_lines))})
            continue

        if re.match(r'^([-*+])\s+', stripped) or re.match(r'^\d+[.)]\s+', stripped):
            flush_paragraph()
            items = []
            while i < len(lines):
                item_line = lines[i].strip()
                unordered = re.match(r'^[-*+]\s+(.+)$', item_line)
                ordered = re.match(r'^(\d+)[.)]\s+(.+)$', item_line)
                if unordered:
                    items.append({'text': _clean_inline_markdown(unordered.group(1)), 'number': None})
                elif ordered:
                    items.append({'text': _clean_inline_markdown(ordered.group(2)), 'number': ordered.group(1)})
                else:
                    break
                i += 1
            blocks.append({'kind': 'list', 'items': items})
            continue

        if stripped.count('|') >= 2:
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().count('|') >= 2:
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for table_line in table_lines:
                cells = [cell.strip() for cell in table_line.strip('|').split('|')]
                if cells and all(re.match(r'^:?-{3,}:?$', cell) for cell in cells):
                    continue
                rows.append([_clean_inline_markdown(cell) for cell in cells])
            if rows:
                blocks.append({'kind': 'table', 'rows': rows})
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return blocks


def _clean_inline_markdown(text: str) -> str:
    math_segments = []

    def stash_math(match):
        math_segments.append(_format_latex_text(match.group(1)))
        return f'@@MATH{len(math_segments) - 1}@@'

    text = re.sub(r'\$(?!\$)([^$\n]+)\$', stash_math, text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'<[^>]+>', '', text)
    for index, value in enumerate(math_segments):
        text = text.replace(f'@@MATH{index}@@', value)
    return text.strip()


def _parse_inline_segments(text: str) -> list[dict]:
    segments = []
    position = 0
    for match in re.finditer(r'\$(?!\$)([^$\n]+)\$', text):
        if match.start() > position:
            plain = _clean_inline_markdown_no_math(text[position:match.start()])
            if plain:
                segments.append({'kind': 'text', 'text': plain})
        tokens = _format_latex_tokens(match.group(1))
        if tokens:
            _mark_compact_math_tokens(tokens)
            segments.append({'kind': 'math', 'tokens': tokens})
        position = match.end()
    if position < len(text):
        plain = _clean_inline_markdown_no_math(text[position:])
        if plain:
            segments.append({'kind': 'text', 'text': plain})
    return segments


def _clean_inline_markdown_no_math(text: str) -> str:
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text


def _iter_inline_atoms(segments: list[dict]):
    for segment in segments:
        if segment['kind'] == 'math':
            for token in segment['tokens']:
                yield {**token, 'math': True}
            continue

        for part in re.findall(r'\s+|[^\s]+', segment['text']):
            yield {'type': 'text', 'text': part, 'math': False}


def _mark_compact_math_tokens(tokens):
    for token in tokens:
        token['compact'] = True
        if token['type'] == 'frac':
            _mark_compact_math_tokens(token['numerator'])
            _mark_compact_math_tokens(token['denominator'])
        elif token['type'] == 'scripted':
            token['base']['compact'] = True
            _mark_compact_math_tokens([token['base']])


def _measure_math_tokens(draw, tokens, normal_font, small_font) -> tuple[int, int]:
    width = 0
    height = _line_height(normal_font) + 14
    for token in tokens:
        token_width, token_height = _measure_math_token(draw, token, normal_font, small_font)
        width += token_width
        height = max(height, token_height)
    return int(width), int(height)


def _measure_math_token(draw, token, normal_font, small_font) -> tuple[int, int]:
    if token['type'] == 'frac':
        if token.get('compact'):
            text = _compact_frac_text(token)
            return int(draw.textlength(text, font=normal_font)), _line_height(normal_font) + 14
        return _measure_frac_token(draw, token, normal_font, small_font)
    if token['type'] == 'scripted':
        return _measure_scripted_token(draw, token, normal_font, small_font)
    font = token.get('plain_font') or (small_font if token['type'] in ('sup', 'sub') else normal_font)
    return int(draw.textlength(token['text'], font=font)), _line_height(font) + 14


def _measure_scripted_token(draw, token, normal_font, small_font) -> tuple[int, int]:
    base_width, base_height = _measure_math_token(draw, token['base'], normal_font, small_font)
    sup_width = int(draw.textlength(token.get('sup') or '', font=small_font))
    sub_width = int(draw.textlength(token.get('sub') or '', font=small_font))
    if _is_display_operator(token):
        width = max(base_width, sup_width, sub_width) + 8
        height = base_height + (18 if token.get('sup') else 0) + (18 if token.get('sub') else 0)
        return width, height
    return base_width + max(sup_width, sub_width) + 4, max(base_height, _line_height(normal_font) + 24)


def _measure_frac_token(draw, token, normal_font, small_font) -> tuple[int, int]:
    numerator_width, numerator_height = _measure_math_tokens(draw, token['numerator'], small_font, small_font)
    denominator_width, denominator_height = _measure_math_tokens(draw, token['denominator'], small_font, small_font)
    width = max(numerator_width, denominator_width) + 14
    height = numerator_height + denominator_height + 10
    return width, height


def _append_wrapped_math_tokens(
    ops,
    draw,
    tokens,
    x,
    y,
    max_width,
    normal_font,
    small_font,
    fill,
    plain_font=None,
    line_gap=10,
):
    lines = []
    current = []
    current_width = 0
    current_height = 0
    base_height = max(_line_height(plain_font or normal_font), _line_height(normal_font)) + line_gap + 8

    for token in tokens:
        token = dict(token)
        if plain_font and not token.get('math') and token['type'] == 'text':
            token['plain_font'] = plain_font
        width, height = _measure_math_token(draw, token, normal_font, small_font)
        if current and current_width + width > max_width:
            lines.append((current, current_height or base_height))
            current = []
            current_width = 0
            current_height = 0
            if token.get('text', '').isspace():
                continue
        current.append((token, width, height))
        current_width += width
        current_height = max(current_height, height, base_height)

    if current:
        lines.append((current, current_height or base_height))

    line_y = y
    for line, height in lines:
        cursor_x = x
        for token, width, token_height in line:
            _append_math_token_ops(ops, draw, token, cursor_x, line_y, height, normal_font, small_font, fill)
            cursor_x += width
        line_y += height
    return line_y


def _append_math_token_ops(ops, draw, token, x, y, line_height, normal_font, small_font, fill):
    if token['type'] == 'frac':
        if token.get('compact'):
            text = _compact_frac_text(token)
            baseline_y = y + max(0, (line_height - (_line_height(normal_font) + 14)) / 2)
            ops.append({'type': 'text', 'xy': (x, baseline_y), 'text': text, 'font': normal_font, 'fill': fill})
            return
        width, height = _measure_frac_token(draw, token, normal_font, small_font)
        _append_frac_ops(ops, draw, token, x, y + max(0, (line_height - height) / 2), normal_font, small_font, fill)
        return

    if token['type'] == 'scripted':
        _append_scripted_token_ops(ops, draw, token, x, y, line_height, normal_font, small_font, fill)
        return

    font = token.get('plain_font') or (small_font if token['type'] in ('sup', 'sub') else normal_font)
    text_height = _line_height(font)
    baseline_y = y + max(0, (line_height - (_line_height(normal_font) + 14)) / 2)
    if token['type'] == 'sup':
        token_y = baseline_y - 8
    elif token['type'] == 'sub':
        token_y = baseline_y + 13
    else:
        token_y = baseline_y
    ops.append({'type': 'text', 'xy': (x, token_y), 'text': token['text'], 'font': font, 'fill': fill})
    if token['type'] == 'overline':
        width = draw.textlength(token['text'], font=font)
        ops.append({'type': 'line', 'xy': (x, token_y + 2, x + width, token_y + 2), 'fill': fill, 'width': 2})


def _append_scripted_token_ops(ops, draw, token, x, y, line_height, normal_font, small_font, fill):
    base_width, base_height = _measure_math_token(draw, token['base'], normal_font, small_font)
    sup = token.get('sup')
    sub = token.get('sub')

    if _is_display_operator(token):
        width, token_height = _measure_scripted_token(draw, token, normal_font, small_font)
        start_y = y + max(0, (line_height - token_height) / 2)
        cursor_y = start_y
        if sup:
            sup_width = draw.textlength(sup, font=small_font)
            ops.append({'type': 'text', 'xy': (x + (width - sup_width) / 2, cursor_y), 'text': sup, 'font': small_font, 'fill': fill})
            cursor_y += 18
        base_x = x + (width - base_width) / 2
        _append_math_token_ops(ops, draw, token['base'], base_x, cursor_y, base_height, normal_font, small_font, fill)
        cursor_y += base_height - 2
        if sub:
            sub_width = draw.textlength(sub, font=small_font)
            ops.append({'type': 'text', 'xy': (x + (width - sub_width) / 2, cursor_y), 'text': sub, 'font': small_font, 'fill': fill})
        return

    baseline_y = y + max(0, (line_height - (_line_height(normal_font) + 14)) / 2)
    _append_math_token_ops(ops, draw, token['base'], x, baseline_y, base_height, normal_font, small_font, fill)
    script_x = x + base_width + 3
    if sup:
        ops.append({'type': 'text', 'xy': (script_x, baseline_y - 11), 'text': sup, 'font': small_font, 'fill': fill})
    if sub:
        ops.append({'type': 'text', 'xy': (script_x, baseline_y + 15), 'text': sub, 'font': small_font, 'fill': fill})


def _is_display_operator(token) -> bool:
    base = token.get('base', {})
    return not token.get('compact') and base.get('type') == 'text' and base.get('text') in ('∑', '∏', '∫')


def _append_math_tokens(ops, draw, tokens, x, y, normal_font, small_font, fill):
    cursor_x = x
    baseline_y = y + 20
    for token in tokens:
        token_width, _ = _measure_math_token(draw, token, normal_font, small_font)
        if token['type'] == 'frac':
            _append_frac_ops(ops, draw, token, cursor_x, y, normal_font, small_font, fill)
        else:
            font = small_font if token['type'] in ('sup', 'sub') else normal_font
            if token['type'] == 'sup':
                token_y = baseline_y - 16
            elif token['type'] == 'sub':
                token_y = baseline_y + 7
            else:
                token_y = baseline_y
            ops.append({'type': 'text', 'xy': (cursor_x, token_y), 'text': token['text'], 'font': font, 'fill': fill})
            if token['type'] == 'overline':
                ops.append({'type': 'line', 'xy': (cursor_x, token_y + 2, cursor_x + token_width, token_y + 2), 'fill': fill, 'width': 2})
        cursor_x += token_width


def _append_frac_ops(ops, draw, token, x, y, normal_font, small_font, fill):
    width, _ = _measure_frac_token(draw, token, normal_font, small_font)
    numerator_width, numerator_height = _measure_math_tokens(draw, token['numerator'], small_font, small_font)
    denominator_width, _ = _measure_math_tokens(draw, token['denominator'], small_font, small_font)
    numerator_x = x + (width - numerator_width) / 2
    denominator_x = x + (width - denominator_width) / 2
    line_y = y + numerator_height - 4
    _append_wrapped_math_tokens(
        ops,
        draw,
        token['numerator'],
        numerator_x,
        y - 10,
        width,
        small_font,
        small_font,
        fill,
    )
    ops.append({'type': 'line', 'xy': (x + 3, line_y, x + width - 3, line_y), 'fill': fill, 'width': 2})
    _append_wrapped_math_tokens(
        ops,
        draw,
        token['denominator'],
        denominator_x,
        line_y - 3,
        width,
        small_font,
        small_font,
        fill,
    )


def _compact_frac_text(token) -> str:
    numerator = _tokens_to_plain_text(token['numerator'])
    denominator = _tokens_to_plain_text(token['denominator'])
    return f'{numerator}/{denominator}'


def _tokens_to_plain_text(tokens) -> str:
    parts = []
    for token in tokens:
        if token['type'] == 'frac':
            parts.append(_compact_frac_text(token))
        elif token['type'] == 'sup':
            parts.append(f'^{token["text"]}')
        elif token['type'] == 'sub':
            parts.append(f'_{token["text"]}')
        elif token['type'] == 'overline':
            parts.append(f'{token["text"]}\u0304')
        else:
            parts.append(token['text'])
    return ''.join(parts)


_SUPERSCRIPT_MAP = str.maketrans({
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
    'A': 'ᴬ', 'B': 'ᴮ', 'D': 'ᴰ', 'E': 'ᴱ', 'G': 'ᴳ',
    'H': 'ᴴ', 'I': 'ᴵ', 'J': 'ᴶ', 'K': 'ᴷ', 'L': 'ᴸ',
    'M': 'ᴹ', 'N': 'ᴺ', 'O': 'ᴼ', 'P': 'ᴾ', 'R': 'ᴿ',
    'Q': 'ᵠ', 'T': 'ᵀ', 'U': 'ᵁ', 'V': 'ⱽ', 'W': 'ᵂ',
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ',
    'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ',
    'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ',
    'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
    'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
})

_SUBSCRIPT_MAP = str.maketrans({
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
    'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
    'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
    'v': 'ᵥ', 'x': 'ₓ',
})


_LATEX_REPLACEMENTS = {
    r'\alpha': 'α',
    r'\beta': 'β',
    r'\gamma': 'γ',
    r'\delta': 'δ',
    r'\epsilon': 'ε',
    r'\theta': 'θ',
    r'\lambda': 'λ',
    r'\mu': 'μ',
    r'\pi': 'π',
    r'\sigma': 'σ',
    r'\tau': 'τ',
    r'\phi': 'φ',
    r'\omega': 'ω',
    r'\Gamma': 'Γ',
    r'\Delta': 'Δ',
    r'\Theta': 'Θ',
    r'\Lambda': 'Λ',
    r'\Pi': 'Π',
    r'\Sigma': 'Σ',
    r'\Phi': 'Φ',
    r'\Omega': 'Ω',
    r'\sum': '∑',
    r'\prod': '∏',
    r'\int': '∫',
    r'\cdots': '⋯',
    r'\ldots': '…',
    r'\infty': '∞',
    r'\leq': '≤',
    r'\le': '≤',
    r'\geq': '≥',
    r'\ge': '≥',
    r'\neq': '≠',
    r'\approx': '≈',
    r'\times': '×',
    r'\cdot': '·',
    r'\odot': '⊙',
    r'\oplus': '⊕',
    r'\to': '→',
    r'\rightarrow': '→',
    r'\left': '',
    r'\right': '',
    r'\exp': 'exp',
    r'\log': 'log',
    r'\sin': 'sin',
    r'\cos': 'cos',
    r'\tan': 'tan',
    r'\max': 'max',
    r'\min': 'min',
}


def _format_latex_text(text: str) -> str:
    """将常见 LaTeX 公式转成图片导出里更易读的文本形式。"""
    text = text.strip()
    text = re.sub(r'^\${1,2}|\${1,2}$', '', text).strip()
    text = re.sub(r'^\\\[|\\\]$', '', text).strip()

    def replace_sqrt(match):
        value = _format_latex_text(match.group(1).strip())
        return f'√({value})'

    text = re.sub(r'\\(?:operatorname|mathrm|mathit|mathbf|boldsymbol|text)\{([^{}]+)\}', r'\1', text)
    text = re.sub(r'\\mathbb\{E\}', 'E', text)
    text = re.sub(r'\\mathbb\{V\}', 'Var', text)
    text = re.sub(r'\\(?:bar|overline|widebar)\{([^{}]+)\}', lambda match: f'{_format_latex_text(match.group(1))}\u0304', text)
    text = re.sub(r'\\sqrt\{([^{}]+)\}', replace_sqrt, text)
    text = _replace_latex_frac(text)

    for source, target in sorted(_LATEX_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, target)

    text = _replace_latex_scripts(text)
    def strip_unknown_command(match):
        return match.group(1)

    text = re.sub(r'\\([A-Za-z]+)', strip_unknown_command, text)
    text = text.replace(r'\{', '{').replace(r'\}', '}')
    text = text.replace('{', '').replace('}', '')
    return text.strip()


def _replace_latex_scripts(text: str) -> str:
    result = []
    index = 0
    while index < len(text):
        marker = text[index]
        if marker not in ('^', '_') or index + 1 >= len(text):
            result.append(marker)
            index += 1
            continue

        value_start = index + 1
        if text[value_start] == '{':
            group = _read_latex_group(text, value_start)
            if group is None:
                result.append(marker)
                index += 1
                continue
            raw_value, next_index = group
        else:
            raw_value = text[value_start]
            next_index = value_start + 1

        value = _format_latex_text(raw_value)
        result.append(_translate_script(value, marker))
        index = next_index
    return ''.join(result)


def _format_latex_tokens(text: str) -> list[dict[str, str]]:
    text = _format_latex_without_scripts(text, keep_overline=True)
    tokens = []
    index = 0
    while index < len(text):
        overline_match = re.match(r'\\(?:bar|overline|widebar)\{([^{}]+)\}', text[index:])
        if overline_match:
            tokens.append({'type': 'overline', 'text': _format_latex_text(overline_match.group(1))})
            index += len(overline_match.group(0))
            continue

        marker = text[index]
        if marker not in ('^', '_') or index + 1 >= len(text):
            start = index
            while (
                index < len(text)
                and not (text[index] in ('^', '_') and index + 1 < len(text))
                and not re.match(r'\\(?:bar|overline|widebar)\{', text[index:])
            ):
                index += 1
            value = text[start:index]
            if value:
                tokens.append({'type': 'text', 'text': value})
            continue

        value_start = index + 1
        if text[value_start] == '{':
            group = _read_latex_group(text, value_start)
            if group is None:
                tokens.append({'type': 'text', 'text': marker})
                index += 1
                continue
            raw_value, next_index = group
        else:
            raw_value = text[value_start]
            next_index = value_start + 1
        tokens.append({'type': 'sup' if marker == '^' else 'sub', 'text': _format_latex_text(raw_value)})
        index = next_index
    return _merge_script_tokens(tokens)


def _merge_script_tokens(tokens: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token['type'] in ('sup', 'sub') or index + 1 >= len(tokens):
            merged.append(token)
            index += 1
            continue

        next_token = tokens[index + 1]
        if next_token['type'] not in ('sup', 'sub'):
            merged.append(token)
            index += 1
            continue

        prefix, base = _split_script_base(token)
        if prefix:
            merged.append(prefix)
            token = base

        scripted = {'type': 'scripted', 'base': token}
        while index + 1 < len(tokens) and tokens[index + 1]['type'] in ('sup', 'sub'):
            script = tokens[index + 1]
            scripted[script['type']] = script['text']
            index += 1
        merged.append(scripted)
        index += 1
    return merged


def _split_script_base(token: dict) -> tuple[dict | None, dict]:
    if token['type'] != 'text':
        return None, token
    text = token.get('text', '')
    if len(text) <= 1:
        return None, token
    base_text = text[-1]
    if not (base_text.isalnum() or base_text in ('∑', '∏', '∫', ')', ']')):
        return None, token
    return {'type': 'text', 'text': text[:-1]}, {'type': 'text', 'text': base_text}


def _translate_script(value: str, marker: str) -> str:
    table = _SUPERSCRIPT_MAP if marker == '^' else _SUBSCRIPT_MAP
    translated = value.translate(table)
    if translated != value and all(char in table or char.isspace() for char in value):
        return translated
    if len(value) == 1 and translated != value:
        return translated
    return f'{marker}({value})'


def _format_latex_without_scripts(text: str, keep_overline: bool = False, keep_frac: bool = False) -> str:
    text = text.strip()
    text = re.sub(r'^\${1,2}|\${1,2}$', '', text).strip()
    text = re.sub(r'^\\\[|\\\]$', '', text).strip()
    text = re.sub(r'\\mathbb\{E\}', 'E', text)
    text = re.sub(r'\\mathbb\{V\}', 'Var', text)
    text = re.sub(r'\\(?:operatorname|mathrm|mathit|mathbf|boldsymbol|text)\{([^{}]+)\}', r'\1', text)
    if not keep_overline:
        text = re.sub(r'\\(?:bar|overline|widebar)\{([^{}]+)\}', lambda match: f'{_format_latex_text(match.group(1))}\u0304', text)
    text = re.sub(
        r'\\sqrt\{([^{}]+)\}',
        lambda match: f'√({_format_latex_without_scripts(match.group(1), keep_overline=keep_overline, keep_frac=keep_frac)})',
        text,
    )
    if not keep_frac:
        text = _replace_latex_frac(text, keep_overline=keep_overline)
    for source, target in sorted(_LATEX_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, target)
    def strip_unknown_command(match):
        command = match.group(1)
        if keep_overline and command in ('bar', 'overline', 'widebar'):
            return f'\\{command}'
        if keep_frac and command == 'frac':
            return f'\\{command}'
        return command

    text = re.sub(r'\\([A-Za-z]+)', strip_unknown_command, text)
    text = text.replace(r'\{', '{').replace(r'\}', '}')
    return text.strip()


def _replace_latex_frac(text: str, keep_overline: bool = False) -> str:
    while '\\frac{' in text:
        start = text.find('\\frac{')
        numerator_start = start + len('\\frac')
        numerator = _read_latex_group(text, numerator_start)
        if numerator is None:
            break
        denominator = _read_latex_group(text, numerator[1])
        if denominator is None:
            break
        numerator_text = _format_latex_without_scripts(numerator[0], keep_overline=keep_overline)
        denominator_text = _format_latex_without_scripts(denominator[0], keep_overline=keep_overline)
        replacement = (
            f'{_maybe_wrap_fraction_part(numerator_text)}'
            f'/{_maybe_wrap_fraction_part(denominator_text)}'
        )
        text = text[:start] + replacement + text[denominator[1]:]
    return text


def _maybe_wrap_fraction_part(text: str) -> str:
    text = text.strip()
    if re.match(r'^[A-Za-z0-9]+(?:[_^][A-Za-z0-9]+)?$', text):
        return text
    if re.match(r'^[A-Za-z0-9]+(?:_\{[^{}]+\}|\^\{[^{}]+\})?$', text):
        return text
    return f'({text})'


def _read_latex_group(text: str, start: int):
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return None


def _wrap_text(draw, text: str, font, max_width: int, preserve_spaces: bool = False) -> list[str]:
    if not preserve_spaces:
        text = re.sub(r'\s+', ' ', text.strip())
    if text == '':
        return ['']

    lines = []
    for raw_line in text.splitlines():
        current = ''
        for char in raw_line:
            candidate = current + char
            if not current or draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current.rstrip() if not preserve_spaces else current)
                current = char.lstrip() if not preserve_spaces else char
        lines.append(current.rstrip() if not preserve_spaces else current)
    return lines or ['']


def _line_height(font) -> int:
    bbox = font.getbbox('字Ay')
    return bbox[3] - bbox[1]


def _mix_color(start: str, end: str, ratio: float) -> tuple[int, int, int]:
    start_rgb = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(round(a + (b - a) * ratio) for a, b in zip(start_rgb, end_rgb))


def _load_font(
    size: int,
    bold: bool = False,
    mono: bool = False,
    serif: bool = False,
    font_id: str | None = None,
):
    candidates = []
    font_config = _EXPORT_IMAGE_FONT_CONFIGS.get(normalize_export_image_font(font_id)) if font_id else None
    if font_config and not mono:
        candidates.extend(font_config['bold' if bold else 'regular'])
    if mono:
        candidates.extend([
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
            '/System/Library/Fonts/PingFang.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            '/System/Library/Fonts/Menlo.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        ])
    if serif and bold:
        candidates.extend([
            '/System/Library/Fonts/Supplemental/Songti.ttc',
            '/System/Library/Fonts/Supplemental/STSong.ttf',
            '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
        ])
    elif serif:
        candidates.extend([
            '/System/Library/Fonts/Supplemental/Songti.ttc',
            '/System/Library/Fonts/Supplemental/STSong.ttf',
            '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        ])
    if bold:
        candidates.extend([
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ])
    candidates.extend([
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ])

    for candidate in candidates:
        path, index = candidate if isinstance(candidate, tuple) else (candidate, 0)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=index)
            except Exception:
                continue
    return ImageFont.load_default()
