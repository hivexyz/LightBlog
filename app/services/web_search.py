from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings


class WebSearchError(RuntimeError):
    """An expected search-provider failure."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str
    source_name: str
    published_at: str = ''


def normalize_public_url(raw_url: str) -> str:
    """Accept only external HTTP(S) URLs and remove fragments."""
    try:
        parsed = urlsplit((raw_url or '').strip())
    except ValueError:
        return ''
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return ''
    hostname = parsed.hostname.rstrip('.').lower()
    if hostname == 'localhost' or hostname.endswith('.localhost') or hostname.endswith('.local'):
        return ''
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
    ):
        return ''
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))


def _clip(value: Any, limit: int) -> str:
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit]


def _normalize_results(raw_results: Any, max_results: int) -> list[SearchResult]:
    if not isinstance(raw_results, list):
        raise WebSearchError('搜索服务没有返回结果列表')
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = normalize_public_url(str(item.get('url') or ''))
        if not url or url in seen_urls:
            continue
        title = _clip(item.get('title'), 500) or urlsplit(url).hostname or '未命名来源'
        snippet = _clip(item.get('snippet') or item.get('content'), 4000)
        content = _clip(item.get('content') or snippet, 15000)
        source_name = _clip(item.get('source_name'), 200) or (urlsplit(url).hostname or '')
        published_at = _clip(item.get('published_at'), 100)
        results.append(SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            content=content,
            source_name=source_name,
            published_at=published_at,
        ))
        seen_urls.add(url)
        if len(results) >= max_results:
            break
    return results


class TavilySearchProvider:
    """Tavily fallback for deployments whose model endpoint has no web tool."""

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not settings.WEB_SEARCH_API_KEY:
            raise WebSearchError('Tavily 搜索未配置，请设置 WEB_SEARCH_API_KEY')
        payload = {
            'api_key': settings.WEB_SEARCH_API_KEY,
            'query': _clip(query, 1000),
            'search_depth': 'advanced',
            'max_results': max_results,
            'include_answer': False,
            'include_raw_content': 'markdown',
        }
        try:
            with httpx.Client(timeout=settings.WEB_SEARCH_TIMEOUT) as client:
                response = client.post(f'{settings.WEB_SEARCH_API_BASE}/search', json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise WebSearchError('网络搜索超时，请稍后重试') from exc
        except httpx.HTTPStatusError as exc:
            raise WebSearchError(f'网络搜索服务请求失败：HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchError('无法连接或解析网络搜索服务响应') from exc

        results = _normalize_tavily_results(data, max_results)
        if not results:
            raise WebSearchError('没有找到可用的公开网页结果')
        return results


class TavilyHubSearchProvider:
    """Tavily Hub proxy using Bearer auth and its nested response envelope."""

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not settings.WEB_SEARCH_API_KEY:
            raise WebSearchError('Tavily Hub 未配置，请设置 WEB_SEARCH_API_KEY')
        payload = {
            'query': _clip(query, 1000),
            'max_results': max_results,
        }
        try:
            with httpx.Client(timeout=settings.WEB_SEARCH_TIMEOUT) as client:
                response = client.post(
                    f'{settings.WEB_SEARCH_API_BASE}/search',
                    headers={
                        'Authorization': f'Bearer {settings.WEB_SEARCH_API_KEY}',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                )
                response.raise_for_status()
                envelope = response.json()
        except httpx.TimeoutException as exc:
            raise WebSearchError('Tavily Hub 搜索超时，请稍后重试') from exc
        except httpx.HTTPStatusError as exc:
            raise WebSearchError(f'Tavily Hub 请求失败：HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchError('无法连接或解析 Tavily Hub 响应') from exc

        if not isinstance(envelope, dict):
            raise WebSearchError('Tavily Hub 返回了不兼容的响应结构')
        if envelope.get('code') not in (None, 0, 200, '0', '200'):
            raise WebSearchError('Tavily Hub 搜索失败')
        wrapper = envelope.get('data')
        if not isinstance(wrapper, dict) or wrapper.get('ok') is not True:
            raise WebSearchError('Tavily Hub 搜索失败')
        data = wrapper.get('data')
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise WebSearchError('Tavily Hub 原始结果不是有效 JSON') from exc
        if not isinstance(data, dict):
            raise WebSearchError('Tavily Hub 没有返回 Tavily 搜索结果')
        results = _normalize_tavily_results(data, max_results)
        if not results:
            raise WebSearchError('没有找到可用的公开网页结果')
        return results


def get_search_provider():
    if settings.WEB_SEARCH_PROVIDER == 'tavily':
        return TavilySearchProvider()
    if settings.WEB_SEARCH_PROVIDER == 'tavily_hub':
        return TavilyHubSearchProvider()
    if not settings.WEB_SEARCH_PROVIDER:
        raise WebSearchError('网络搜索未配置，请设置 WEB_SEARCH_PROVIDER、WEB_SEARCH_API_BASE 和 WEB_SEARCH_API_KEY')
    raise WebSearchError(f'不支持的搜索 Provider：{settings.WEB_SEARCH_PROVIDER}')


def _normalize_tavily_results(data: dict, max_results: int) -> list[SearchResult]:
    raw_results = []
    for item in data.get('results') or []:
        if not isinstance(item, dict):
            continue
        raw_results.append({
            'title': item.get('title'),
            'url': item.get('url'),
            'snippet': item.get('content'),
            'content': item.get('raw_content') or item.get('content'),
            'source_name': urlsplit(item.get('url') or '').hostname or '',
            'published_at': item.get('published_date') or '',
        })
    return _normalize_results(raw_results, max_results)
