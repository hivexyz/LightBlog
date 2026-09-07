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


def normalize_export_image_template(template: str | None) -> str:
    return template if template in _EXPORT_IMAGE_TEMPLATE_CONFIGS else 'paper'


def _get_export_image_template(template: str | None) -> dict:
    return _EXPORT_IMAGE_TEMPLATE_CONFIGS[normalize_export_image_template(template)]


def export_markdown_chapter_images(
    title: str,
    content: str,
    created_at=None,
    image_roots: dict[str, str] | None = None,
    template: str = 'paper',
) -> list[tuple[str, bytes]]:
    """将 Markdown 按 # / ## 章节拆分并导出为 PNG 长图。"""
    chapters = _split_markdown_chapters(content)
    total = len(chapters)
    images = []
    for index, chapter in enumerate(chapters, start=1):
        renderer = _MarkdownImageRenderer(
            image_roots=image_roots or {},
            template=_get_export_image_template(template),
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
) -> bytes:
    """渲染第一章预览 PNG，供后台模板选择弹窗使用。"""
    chapters = _split_markdown_chapters(content)
    chapter = chapters[0] if chapters else {'title': '全文', 'content': content or ''}
    renderer = _MarkdownImageRenderer(
        image_roots=image_roots or {},
        template=_get_export_image_template(template),
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

    def __init__(self, image_roots: dict[str, str], template: dict):
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
            'title': _load_font(54, bold=True, serif=serif),
            'eyebrow': _load_font(22, serif=serif),
            'meta': _load_font(21, serif=serif),
            'h1': _load_font(39, bold=True, serif=serif),
            'h2': _load_font(34, bold=True, serif=serif),
            'h3': _load_font(29, bold=True, serif=serif),
            'body': _load_font(26, serif=serif),
            'bold': _load_font(26, bold=True, serif=serif),
            'small': _load_font(21),
            'code': _load_font(21, mono=True),
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

        math_text = _format_latex_text(text) or '$$'
        for raw_line in math_text.splitlines():
            lines = _wrap_text(draw, raw_line.strip(), self.fonts['code'], self.content_width - pad_x * 2)
            line_height = _line_height(self.fonts['code']) + 10
            for line in lines:
                ops.append({
                    'type': 'text',
                    'xy': (x + pad_x, y),
                    'text': line,
                    'font': self.fonts['code'],
                    'fill': self.ink,
                })
                y += line_height

        y += pad_y
        box['xy'][3] = y
        return y + 24

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


def _parse_markdown_blocks(content: str) -> list[dict]:
    blocks = []
    lines = content.splitlines()
    paragraph = []
    i = 0

    def flush_paragraph():
        if paragraph:
            text = _clean_inline_markdown(' '.join(line.strip() for line in paragraph))
            if text:
                blocks.append({'kind': 'paragraph', 'text': text})
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


def _format_latex_text(text: str) -> str:
    """将常见 LaTeX 公式转成图片导出里更易读的纯文本。"""
    text = text.strip()
    text = re.sub(r'^\${1,2}|\${1,2}$', '', text).strip()

    def replace_frac(match):
        numerator = match.group(1).strip()
        denominator = match.group(2).strip()
        return f'({numerator}) / ({denominator})'

    text = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', replace_frac, text)

    replacements = {
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
        r'\infty': '∞',
        r'\leq': '≤',
        r'\le': '≤',
        r'\geq': '≥',
        r'\ge': '≥',
        r'\neq': '≠',
        r'\approx': '≈',
        r'\times': '×',
        r'\cdot': '·',
        r'\to': '→',
        r'\rightarrow': '→',
        r'\left': '',
        r'\right': '',
        r'\exp': 'exp',
        r'\log': 'log',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    text = re.sub(r'_\{([^{}]+)\}', r'_(\1)', text)
    text = re.sub(r'\^\{([^{}]+)\}', r'^\1', text)
    text = re.sub(r'\\([A-Za-z]+)', r'\1', text)
    text = text.replace(r'\{', '{').replace(r'\}', '}')
    text = text.replace('{', '').replace('}', '')
    return text.strip()


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


def _load_font(size: int, bold: bool = False, mono: bool = False, serif: bool = False):
    candidates = []
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

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()
