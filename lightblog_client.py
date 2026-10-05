"""
LightBlog 客户端插件
====================

一个用于访问和管理 LightBlog 博客的 Python 客户端。

特性:
- 支持公开内容读取（首页、文章、归档、搜索等）
- 支持后台管理（登录、发文、分类、标签、设置、图片上传）
- 自动处理 session cookie 和 CSRF token
- 兼容服务器对 curl 的拦截（使用 httpx）

用法:
    # 作为库使用
    from lightblog_client import LightBlogClient

    client = LightBlogClient('http://121.40.196.77', 'admin', 'admin123')
    client.login()
    client.create_post(title='你好', content='# Hello World')

    # 作为 CLI 使用
    python lightblog_client.py --url http://121.40.196.77 -u admin -p admin123 post list
"""

from __future__ import annotations

import re
import json
import argparse
import mimetypes
from pathlib import Path
from typing import Optional

import httpx


class LightBlogError(Exception):
    """LightBlog 客户端异常"""


class LightBlogClient:
    """LightBlog 博客客户端"""

    def __init__(
        self,
        base_url: str,
        username: str = '',
        password: str = '',
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={
                'User-Agent': 'Mozilla/5.0 (LightBlog-Client/1.0)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            },
        )
        self._csrf_token: Optional[str] = None
        self._logged_in = False

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_csrf(html: str) -> str:
        """从 HTML 表单中提取 csrf_token"""
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        if m:
            return m.group(1)
        # 也可能以 JS 变量形式存在: const csrfToken = '...'
        m = re.search(r"csrfToken\s*=\s*'([^']+)'", html)
        if m:
            return m.group(1)
        raise LightBlogError('无法从页面中提取 CSRF token')

    def _refresh_csrf(self) -> str:
        """从后台页面刷新 CSRF token

        dashboard 页面没有表单，因此从有表单的页面（如文章列表）获取。
        """
        for path in ('/admin/posts', '/admin/categories', '/admin/settings'):
            r = self._client.get(path)
            if r.status_code == 200:
                try:
                    self._csrf_token = self._extract_csrf(r.text)
                    return self._csrf_token
                except LightBlogError:
                    continue
        raise LightBlogError('无法从后台页面获取 CSRF token')

    def _post(self, path: str, data: Optional[dict] = None, files: Optional[dict] = None) -> httpx.Response:
        """带 CSRF token 的 POST 请求，失败时自动刷新 token 重试一次"""
        if not self._csrf_token:
            self._refresh_csrf()
        data = dict(data or {})
        data['csrf_token'] = self._csrf_token
        r = self._client.post(path, data=data, files=files)
        # CSRF 失效时刷新重试
        if r.status_code == 400 and 'CSRF' in r.text:
            self._refresh_csrf()
            data['csrf_token'] = self._csrf_token
            r = self._client.post(path, data=data, files=files)
        return r

    # ------------------------------------------------------------------
    # 认证
    # ------------------------------------------------------------------

    def login(self) -> None:
        """登录后台"""
        if not self.username or not self.password:
            raise LightBlogError('需要提供用户名和密码')

        # 1. 获取登录页 CSRF token
        r = self._client.get('/admin/login')
        r.raise_for_status()
        csrf = self._extract_csrf(r.text)

        # 2. 提交登录
        r = self._client.post('/admin/login', data={
            'username': self.username,
            'password': self.password,
            'csrf_token': csrf,
        })

        # 登录成功会 302 到 /admin/；失败则返回登录页（含错误信息）
        if '/admin/login' in str(r.url):
            m = re.search(r'class="alert[^"]*">([^<]+)<', r.text)
            msg = m.group(1).strip() if m else '登录失败'
            raise LightBlogError(msg)

        # 3. 刷新绑定 session 的 CSRF token
        self._refresh_csrf()
        self._logged_in = True

    def logout(self) -> None:
        """退出登录"""
        self._client.get('/admin/logout')
        self._csrf_token = None
        self._logged_in = False

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    # ------------------------------------------------------------------
    # 公开内容读取
    # ------------------------------------------------------------------

    def get_homepage(self, page: int = 1) -> str:
        """获取首页 HTML"""
        r = self._client.get('/', params={'page': page})
        r.raise_for_status()
        return r.text

    def get_post(self, slug: str) -> str:
        """获取文章详情 HTML"""
        r = self._client.get(f'/post/{slug}')
        if r.status_code == 404:
            raise LightBlogError(f'文章不存在: {slug}')
        r.raise_for_status()
        return r.text

    def get_archive(self) -> str:
        """获取归档页 HTML"""
        r = self._client.get('/archive')
        r.raise_for_status()
        return r.text

    def get_about(self) -> str:
        """获取关于页 HTML"""
        r = self._client.get('/about')
        r.raise_for_status()
        return r.text

    def search(self, q: str, page: int = 1) -> str:
        """搜索文章"""
        r = self._client.get('/search', params={'q': q, 'page': page})
        r.raise_for_status()
        return r.text

    def get_category(self, slug: str, page: int = 1) -> str:
        """获取分类下的文章"""
        r = self._client.get(f'/category/{slug}', params={'page': page})
        if r.status_code == 404:
            raise LightBlogError(f'分类不存在: {slug}')
        r.raise_for_status()
        return r.text

    def get_tag(self, slug: str, page: int = 1) -> str:
        """获取标签下的文章"""
        r = self._client.get(f'/tag/{slug}', params={'page': page})
        if r.status_code == 404:
            raise LightBlogError(f'标签不存在: {slug}')
        r.raise_for_status()
        return r.text

    def get_feed(self) -> str:
        """获取 RSS feed"""
        r = self._client.get('/feed.xml')
        r.raise_for_status()
        return r.text

    # ------------------------------------------------------------------
    # 后台 - 文章
    # ------------------------------------------------------------------

    def create_post(
        self,
        title: str,
        content: str,
        category_id: Optional[int] = None,
        tag_ids: Optional[list[int]] = None,
        status: int = 1,
        cover_image: str = '',
    ) -> None:
        """创建文章

        Args:
            title: 标题
            content: Markdown 内容
            category_id: 分类 ID
            tag_ids: 标签 ID 列表
            status: 0=草稿, 1=已发布
            cover_image: 封面图 URL
        """
        data = {
            'title': title,
            'content': content,
            'status': str(status),
            'cover_image': cover_image,
        }
        if category_id is not None:
            data['category_id'] = str(category_id)
        if tag_ids:
            data['tag_ids'] = [str(t) for t in tag_ids]

        r = self._post('/admin/post/new', data=data)
        if r.status_code != 200 or '/admin/posts' not in str(r.url):
            raise LightBlogError(f'创建文章失败: {r.status_code}')

    def update_post(
        self,
        post_id: int,
        title: str,
        content: str,
        category_id: Optional[int] = None,
        tag_ids: Optional[list[int]] = None,
        status: int = 1,
        cover_image: str = '',
    ) -> None:
        """更新文章"""
        data = {
            'title': title,
            'content': content,
            'status': str(status),
            'cover_image': cover_image,
        }
        if category_id is not None:
            data['category_id'] = str(category_id)
        if tag_ids:
            data['tag_ids'] = [str(t) for t in tag_ids]
        # tag_ids 为空时不发送该字段，由服务器决定行为

        r = self._post(f'/admin/post/{post_id}/edit', data=data)
        if r.status_code != 200 or '/admin/posts' not in str(r.url):
            raise LightBlogError(f'更新文章失败: {r.status_code}')

    def delete_post(self, post_id: int) -> None:
        """删除文章"""
        r = self._post(f'/admin/post/{post_id}/delete')
        if r.status_code != 200:
            raise LightBlogError(f'删除文章失败: {r.status_code}')

    def list_posts(self, page: int = 1) -> str:
        """获取后台文章列表页 HTML"""
        r = self._client.get('/admin/posts', params={'page': page})
        r.raise_for_status()
        return r.text

    # ------------------------------------------------------------------
    # 后台 - 分类
    # ------------------------------------------------------------------

    def create_category(self, name: str, description: str = '') -> None:
        """创建分类"""
        r = self._post('/admin/categories', data={
            'name': name,
            'description': description,
        })
        if r.status_code != 200:
            raise LightBlogError(f'创建分类失败: {r.status_code}')

    def delete_category(self, category_id: int) -> None:
        """删除分类"""
        r = self._post(f'/admin/category/{category_id}/delete')
        if r.status_code != 200:
            raise LightBlogError(f'删除分类失败: {r.status_code}')

    # ------------------------------------------------------------------
    # 后台 - 标签
    # ------------------------------------------------------------------

    def create_tag(self, name: str) -> None:
        """创建标签"""
        r = self._post('/admin/tags', data={'name': name})
        if r.status_code != 200:
            raise LightBlogError(f'创建标签失败: {r.status_code}')

    def delete_tag(self, tag_id: int) -> None:
        """删除标签"""
        r = self._post(f'/admin/tag/{tag_id}/delete')
        if r.status_code != 200:
            raise LightBlogError(f'删除标签失败: {r.status_code}')

    # ------------------------------------------------------------------
    # 后台 - 设置
    # ------------------------------------------------------------------

    def update_settings(
        self,
        site_title: str = '',
        site_subtitle: str = '',
        site_description: str = '',
        site_avatar: str = '',
        github_url: str = '',
        about_content: str = '',
    ) -> None:
        """更新站点设置"""
        data = {
            'site_title': site_title,
            'site_subtitle': site_subtitle,
            'site_description': site_description,
            'site_avatar': site_avatar,
            'github_url': github_url,
            'about_content': about_content,
        }
        r = self._post('/admin/settings', data=data)
        if r.status_code != 200:
            raise LightBlogError(f'更新设置失败: {r.status_code}')

    # ------------------------------------------------------------------
    # 后台 - 图片上传
    # ------------------------------------------------------------------

    def upload_image(self, file_path: str) -> str:
        """上传图片，返回图片 URL"""
        path = Path(file_path)
        if not path.exists():
            raise LightBlogError(f'文件不存在: {file_path}')

        content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        with open(path, 'rb') as f:
            files = {'file': (path.name, f, content_type)}
            r = self._post('/admin/upload', files=files)

        if r.status_code != 200:
            raise LightBlogError(f'上传失败: {r.status_code} {r.text}')
        return r.json().get('url', '')

    # ------------------------------------------------------------------
    # 上下文管理
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ======================================================================
# CLI 入口
# ======================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='lightblog_client',
        description='LightBlog 博客客户端',
    )
    parser.add_argument('--url', required=True, help='博客地址，如 http://121.40.196.77')
    parser.add_argument('-u', '--username', default='', help='管理员用户名')
    parser.add_argument('-p', '--password', default='', help='管理员密码')

    sub = parser.add_subparsers(dest='command', required=True)

    # 公开读取
    sub.add_parser('home', help='获取首页')
    sub.add_parser('archive', help='获取归档')
    sub.add_parser('about', help='获取关于页')
    sub.add_parser('feed', help='获取 RSS')

    p = sub.add_parser('post', help='读取文章')
    p.add_argument('slug', help='文章 slug')

    p = sub.add_parser('search', help='搜索文章')
    p.add_argument('q', help='关键词')

    # 后台 - 文章
    p = sub.add_parser('post-list', help='后台文章列表')
    p.add_argument('--page', type=int, default=1)

    p = sub.add_parser('post-create', help='创建文章')
    p.add_argument('--title', required=True)
    p.add_argument('--content', required=True, help='Markdown 内容')
    p.add_argument('--category-id', type=int, default=None)
    p.add_argument('--tag-ids', type=int, nargs='*', default=None)
    p.add_argument('--status', type=int, default=1, help='0=草稿 1=已发布')
    p.add_argument('--cover', default='')

    p = sub.add_parser('post-delete', help='删除文章')
    p.add_argument('id', type=int)

    # 后台 - 分类
    p = sub.add_parser('category-create', help='创建分类')
    p.add_argument('name')
    p.add_argument('--desc', default='')

    p = sub.add_parser('category-delete', help='删除分类')
    p.add_argument('id', type=int)

    # 后台 - 标签
    p = sub.add_parser('tag-create', help='创建标签')
    p.add_argument('name')

    p = sub.add_parser('tag-delete', help='删除标签')
    p.add_argument('id', type=int)

    # 后台 - 上传
    p = sub.add_parser('upload', help='上传图片')
    p.add_argument('file')

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    client = LightBlogClient(args.url, args.username, args.password)

    # 需要登录的命令
    admin_commands = {
        'post-list', 'post-create', 'post-delete',
        'category-create', 'category-delete',
        'tag-create', 'tag-delete',
        'upload',
    }

    try:
        if args.command in admin_commands:
            client.login()

        if args.command == 'home':
            print(client.get_homepage())
        elif args.command == 'archive':
            print(client.get_archive())
        elif args.command == 'about':
            print(client.get_about())
        elif args.command == 'feed':
            print(client.get_feed())
        elif args.command == 'post':
            print(client.get_post(args.slug))
        elif args.command == 'search':
            print(client.search(args.q))
        elif args.command == 'post-list':
            print(client.list_posts(args.page))
        elif args.command == 'post-create':
            client.create_post(
                title=args.title,
                content=args.content,
                category_id=args.category_id,
                tag_ids=args.tag_ids,
                status=args.status,
                cover_image=args.cover,
            )
            print('文章创建成功')
        elif args.command == 'post-delete':
            client.delete_post(args.id)
            print('文章已删除')
        elif args.command == 'category-create':
            client.create_category(args.name, args.desc)
            print('分类创建成功')
        elif args.command == 'category-delete':
            client.delete_category(args.id)
            print('分类已删除')
        elif args.command == 'tag-create':
            client.create_tag(args.name)
            print('标签创建成功')
        elif args.command == 'tag-delete':
            client.delete_tag(args.id)
            print('标签已删除')
        elif args.command == 'upload':
            url = client.upload_image(args.file)
            print(f'上传成功: {url}')
    except LightBlogError as e:
        print(f'错误: {e}', flush=True)
        raise SystemExit(1)
    finally:
        client.close()


if __name__ == '__main__':
    main()
