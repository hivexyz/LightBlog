import base64
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_session as create_login_session
from app.auth import generate_csrf_token, get_csrf_nonce
from app.config import settings
from app.database import Base, get_db
from app.models import AIWritingJob, AIWritingSession, User
from app.routes.admin import router as admin_router
from app.routes.ai_writing import router
from app.auth import require_admin
from app.services.ai_writer import (
    AIWriterError,
    ImagePlan,
    OpenAICompatibleWriter,
    assemble_final_content,
    ensure_image_slots,
    normalize_image_plans,
    parse_json_object,
    save_generated_image,
)
from app.services.web_search import SearchResult, TavilyHubSearchProvider, normalize_public_url
from app.services.ai_job_worker import process_job, recover_stale_jobs


class ImageRecord:
    image_type = 'illustration'
    slot = 'figure_1'
    status = 'ready'
    file_path = '/uploads/2026/09/example.webp'
    alt_text = '示例配图'


class PendingImageRecord:
    image_type = 'illustration'
    slot = 'figure_2'
    status = 'planned'
    file_path = ''
    alt_text = '待生成配图'


class FakeWriter:
    def generate_draft(self, **kwargs):
        sources = list(kwargs.get('research_sources') or [])
        if sources:
            content = (
                f'## 初稿\n\n[可信来源]({sources[0]["url"]})支持这个结论。'
                '\n\n[未选择来源](https://untrusted.example/article)'
            )
        else:
            content = '## 初稿\n\n这是初稿。'
        return {'title': '测试初稿', 'content': content}

    def plan_research(self, **kwargs):
        return [
            {'query': '官方技术文档', 'purpose': '核实技术结论'},
            {'query': '相关原始论文', 'purpose': '寻找一手证据'},
        ]

    def interview(self, **kwargs):
        sources = list(kwargs.get('research_sources') or [])
        source_note = f' [资料]({sources[0]["url"]})' if sources else ''
        return {
            'reply': f'这个案例可以成为文章的核心证据。{source_note}',
            'questions': ['这个方案在哪些情况下不成立？'],
            'confirmed_brief': '- 作者提供了一个真实项目案例',
        }

    def generate_final_article(self, **kwargs):
        sources = list(kwargs.get('research_sources') or [])
        citation_text = ''
        if sources:
            citation_text = (
                f'\n\n[最终稿可信引用]({sources[0]["url"]})'
                '\n\n[最终稿未选引用](https://untrusted.example/final)'
            )
        return {
            'title': '测试最终稿',
            'content': f'## 结论\n\n最终内容。{citation_text}',
        }

    def plan_images(self, **kwargs):
        return {
            'content': f'{kwargs["content"]}\n\n<!-- AI_IMAGE:figure_1 -->',
            'images': [
                ImagePlan('cover', 'cover', '封面，无文字', '测试封面', '', '16:9'),
                ImagePlan('figure_1', 'illustration', '正文插画，无文字', '正文示意图', '结论', '3:2'),
            ],
        }

    def humanize_article(self, **kwargs):
        return {
            'title': '更像作者的标题',
            'content': kwargs['content'].replace('最终内容。', '我更愿意把这个问题说得直接一点。'),
            'summary': '删除重复总结，保留作者主体和具体判断。',
        }

    def generate_image(self, prompt, aspect_ratio):
        image = Image.new('RGB', (80, 50), '#274060')
        buffer = BytesIO()
        image.save(buffer, 'PNG')
        return buffer.getvalue()


class FakeSearchProvider:
    def __init__(self):
        self.calls = []

    def search(self, query, max_results):
        self.calls.append(query)
        return [
            SearchResult(
                title='官方文档',
                url='https://docs.example.com/guide',
                snippet='官方资料摘要',
                content='官方资料中的完整证据。',
                source_name='docs.example.com',
                published_at='2026-09-01',
            ),
            SearchResult(
                title='原始论文',
                url='https://papers.example.com/research',
                snippet='论文摘要',
                content='论文中的关键结论。',
                source_name='papers.example.com',
            ),
        ][:max_results]


class AIWriterHelpersTest(unittest.TestCase):
    def test_parse_fenced_json(self):
        result = parse_json_object('```json\n{"title":"文章"}\n```')
        self.assertEqual(result['title'], '文章')

    def test_parse_invalid_json_has_clear_error(self):
        with self.assertRaises(AIWriterError):
            parse_json_object('not-json')

    def test_normalize_and_insert_image_plans(self):
        plans = normalize_image_plans(
            [{'type': 'illustration', 'prompt': '知识网络', 'after_heading': '分析', 'alt': '网络'}],
            include_cover=True,
            inline_image_count=1,
            topic='RAG',
            image_style='几何',
        )
        self.assertEqual([plan.slot for plan in plans], ['cover', 'figure_1'])
        self.assertIn('不要出现文字', plans[1].prompt)
        content = ensure_image_slots('## 分析\n\n正文', plans)
        self.assertIn('<!-- AI_IMAGE:figure_1 -->', content)

    def test_assemble_replaces_or_removes_markers(self):
        source = '正文\n\n<!-- AI_IMAGE:figure_1 -->\n\n<!-- AI_IMAGE:figure_2 -->'
        result = assemble_final_content(source, [ImageRecord(), PendingImageRecord()], remove_pending=True)
        self.assertIn('![示例配图](/uploads/2026/09/example.webp)', result)
        self.assertNotIn('AI_IMAGE', result)

    def test_save_generated_image_as_webp(self):
        image = Image.new('RGB', (2000, 1200), 'white')
        buffer = BytesIO()
        image.save(buffer, 'PNG')
        with tempfile.TemporaryDirectory() as directory:
            url = save_generated_image(buffer.getvalue(), directory)
            target = Path(directory) / url.removeprefix('/uploads/')
            self.assertTrue(target.exists())
            with Image.open(target) as saved:
                self.assertEqual(saved.format, 'WEBP')
                self.assertLessEqual(max(saved.size), 1600)

    def test_admin_template_contains_complete_ai_workflow(self):
        environment = Environment(loader=FileSystemLoader('app/templates'))
        html = environment.get_template('admin/post_form.html').render(
            post=None,
            categories=[],
            tags=[],
            csrf_token='test-token',
            ai_text_enabled=True,
            ai_image_enabled=True,
            web_search_enabled=True,
            ai_max_inline_images=2,
        )
        self.assertIn('id="ai-generate-draft"', html)
        self.assertIn('<details', html)
        self.assertIn('id="ai-send"', html)
        self.assertIn('id="ai-plan-research"', html)
        self.assertIn('id="ai-search"', html)
        self.assertIn('id="ai-finalize"', html)
        self.assertIn('id="ai-generate-all-images"', html)
        self.assertIn('id="ai-apply-final"', html)
        self.assertIn('id="ai-writing-mode"', html)
        self.assertIn('id="ai-humanize"', html)
        self.assertIn('id="ai-humanize-diff"', html)
        stage_positions = [
            html.index('data-ai-stage="brief"'),
            html.index('data-ai-stage="research"'),
            html.index('data-ai-stage="interview"'),
            html.index('data-ai-stage="final"'),
        ]
        self.assertEqual(stage_positions, sorted(stage_positions))
        self.assertEqual(html.count('data-ai-stage='), 4)
        self.assertIn('data-ai-stage="brief" open', html)
        self.assertNotIn('data-ai-stage="research" open', html)

    def test_openai_compatible_text_contract(self):
        def handler(request):
            self.assertEqual(request.url.path, '/v1/chat/completions')
            self.assertEqual(request.headers['authorization'], 'Bearer test-key')
            return httpx.Response(200, json={
                'choices': [{'message': {'content': '{"title":"标题","content":"## 正文"}'}}]
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(settings, 'AI_API_BASE', 'https://model.example/v1'), \
                patch.object(settings, 'AI_API_KEY', 'test-key'), \
                patch.object(settings, 'AI_TEXT_MODEL', 'test-model'), \
                patch('app.services.ai_writer.httpx.Client', return_value=client):
            result = OpenAICompatibleWriter().generate_draft(
                topic='主题',
                core_points='观点',
                target_audience='读者',
                desired_length='短文',
            )
        self.assertEqual(result, {'title': '标题', 'content': '## 正文'})

    def test_openai_compatible_base64_image_contract(self):
        image = Image.new('RGB', (20, 10), '#274060')
        buffer = BytesIO()
        image.save(buffer, 'PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')

        def handler(request):
            self.assertEqual(request.url.path, '/v1/images/generations')
            return httpx.Response(200, json={'data': [{'b64_json': encoded}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(settings, 'AI_API_BASE', 'https://model.example/v1'), \
                patch.object(settings, 'AI_API_KEY', 'test-key'), \
                patch.object(settings, 'AI_IMAGE_MODEL', 'test-image-model'), \
                patch('app.services.ai_writer.httpx.Client', return_value=client):
            result = OpenAICompatibleWriter().generate_image('插画，无文字', '3:2')
        self.assertEqual(result, buffer.getvalue())

    def test_final_article_and_image_plan_use_separate_bounded_calls(self):
        writer = OpenAICompatibleWriter()
        calls = []

        def fake_chat(prompt, max_tokens):
            calls.append((prompt, max_tokens))
            if '只负责文章' in prompt:
                return {'title': '分阶段文章', 'content': '## 正文\n\n内容'}
            return {'images': [{
                'type': 'illustration',
                'prompt': '概念插画，不要出现文字',
                'alt': '概念插画',
                'after_heading': '正文',
            }]}

        writer._chat_json = fake_chat
        article = writer.generate_final_article(
            topic='主题',
            core_points='观点',
            current_content='当前稿',
            confirmed_brief='确认要点',
            recent_messages=[],
        )
        image_plan = writer.plan_images(
            topic='主题',
            title=article['title'],
            content=article['content'],
            include_cover=False,
            inline_image_count=1,
            image_style='极简',
        )
        self.assertEqual([call[1] for call in calls], [
            settings.AI_FINAL_MAX_TOKENS,
            settings.AI_IMAGE_PLAN_MAX_TOKENS,
        ])
        self.assertNotIn('AI_IMAGE', article['content'])
        self.assertIn('<!-- AI_IMAGE:figure_1 -->', image_plan['content'])
        self.assertIn('不要默认使用“结论先行”', calls[0][0])
        self.assertIn('个人判断', calls[0][0])

    def test_search_url_filter_rejects_internal_addresses(self):
        self.assertEqual(normalize_public_url('https://example.com/doc#part'), 'https://example.com/doc')
        self.assertEqual(normalize_public_url('http://127.0.0.1/private'), '')
        self.assertEqual(normalize_public_url('http://169.254.169.254/latest/meta-data'), '')

    def test_web_search_requires_explicit_provider_configuration(self):
        with patch.object(settings, 'WEB_SEARCH_PROVIDER', ''), \
                patch.object(settings, 'WEB_SEARCH_API_BASE', ''), \
                patch.object(settings, 'WEB_SEARCH_API_KEY', ''):
            self.assertFalse(settings.WEB_SEARCH_ENABLED)

    def test_tavily_hub_bearer_and_nested_response_contract(self):
        def handler(request):
            self.assertEqual(request.url.path, '/api/proxy/search')
            self.assertEqual(request.headers['authorization'], 'Bearer hub-key')
            return httpx.Response(200, json={
                'code': 0,
                'data': {
                    'ok': True,
                    'data': {
                        'results': [{
                            'title': 'Tavily Hub 结果',
                            'url': 'https://example.com/result',
                            'content': '结果摘要',
                            'score': 0.9,
                        }],
                    },
                },
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(settings, 'WEB_SEARCH_API_BASE', 'https://hub.example/api/proxy'), \
                patch.object(settings, 'WEB_SEARCH_API_KEY', 'hub-key'), \
                patch('app.services.web_search.httpx.Client', return_value=client):
            results = TavilyHubSearchProvider().search('测试问题', 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, 'Tavily Hub 结果')


class AIWritingWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        db = self.Session()
        self.user = User(id=1, username='admin', password_hash='test', is_admin=True)
        db.add(self.user)
        db.commit()
        db.close()

        app = FastAPI()
        app.state.templates = Jinja2Templates(directory='app/templates')
        app.include_router(admin_router)
        app.include_router(router)

        def override_db():
            db_session = self.Session()
            try:
                yield db_session
            finally:
                db_session.close()

        def override_admin():
            return self.user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = override_admin
        self.client = TestClient(app)
        cookie = create_login_session(1)
        self.client.cookies.set('session', cookie)
        self.csrf = generate_csrf_token(get_csrf_nonce(cookie))
        self.headers = {'X-CSRF-Token': self.csrf}
        self.upload_tmp = tempfile.TemporaryDirectory()
        self.old_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.upload_tmp.name
        self.writer_patch = patch('app.routes.ai_writing.OpenAICompatibleWriter', FakeWriter)
        self.writer_patch.start()
        self.fake_search = FakeSearchProvider()
        self.search_patch = patch('app.routes.ai_writing.get_search_provider', return_value=self.fake_search)
        self.search_patch.start()

    def tearDown(self):
        self.writer_patch.stop()
        self.search_patch.stop()
        settings.UPLOAD_DIR = self.old_upload_dir
        self.upload_tmp.cleanup()
        self.client.close()

    def submit_and_run_finalize(self, session_id, payload=None, writer_factory=FakeWriter):
        request_payload = {
            'current_content': '## 当前稿',
            'confirmed_brief': '',
            'include_cover': True,
            'inline_image_count': 1,
            'image_style': '极简',
        }
        request_payload.update(payload or {})
        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/finalize',
            headers=self.headers,
            json=request_payload,
        )
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()['job']
        self.assertEqual(job['status'], 'queued')
        pending = self.client.get(f'/admin/ai-writing/sessions/{session_id}')
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(pending.json()['active_job']['id'], job['id'])
        process_job(
            job['id'],
            session_factory=self.Session,
            writer_factory=writer_factory,
        )
        result = self.client.get(f'/admin/ai-writing/jobs/{job["id"]}')
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_stale_job_resumes_from_saved_article(self):
        class ResumeOnlyWriter(FakeWriter):
            def generate_final_article(self, **kwargs):
                raise AssertionError('已保存文章不应重复生成')

        db = self.Session()
        writing_session = AIWritingSession(
            author_id=1,
            topic='恢复测试',
            core_points='从已保存文章继续',
            final_title='已经生成的标题',
            final_content='## 已保存文章',
            status='planning_images',
        )
        db.add(writing_session)
        db.flush()
        job = AIWritingJob(
            session_id=writing_session.id,
            author_id=1,
            status='running',
            phase='planning_images',
            progress=70,
            attempts=1,
            payload_json='{"include_cover": false, "inline_image_count": 0}',
            updated_at=datetime.utcnow() - timedelta(seconds=1000),
        )
        db.add(job)
        db.commit()
        job_id = job.id
        db.close()

        recovered = recover_stale_jobs(self.Session)
        self.assertEqual(recovered, 1)
        process_job(job_id, session_factory=self.Session, writer_factory=ResumeOnlyWriter)

        db = self.Session()
        stored_job = db.query(AIWritingJob).filter(AIWritingJob.id == job_id).one()
        stored_session = db.query(AIWritingSession).filter(
            AIWritingSession.id == stored_job.session_id
        ).one()
        self.assertEqual(stored_job.status, 'succeeded')
        self.assertEqual(stored_session.final_content, '## 已保存文章')
        self.assertEqual(stored_session.status, 'final_ready')
        db.close()

    def test_complete_interview_and_illustrated_final_workflow(self):
        response = self.client.post('/admin/ai-writing/sessions', headers=self.headers, json={
            'topic': '测试主题',
            'core_points': '核心观点',
            'target_audience': '技术读者',
            'desired_length': '中等',
            'source_content': '',
        })
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()['id']

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/draft',
            headers=self.headers,
            json={'current_content': ''},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['draft_title'], '测试初稿')

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/interview',
            headers=self.headers,
            json={
                'user_message': '这是我的真实案例。',
                'confirmed_brief': '',
                'current_content': '## 手工修改后的初稿',
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('真实项目案例', response.json()['confirmed_brief'])
        self.assertEqual(response.json()['current_content'], '## 手工修改后的初稿')
        self.assertEqual(len(response.json()['messages']), 3)

        async_result = self.submit_and_run_finalize(session_id, {
                'current_content': '## 当前稿\n\n作者修改后的内容。',
                'confirmed_brief': '- 已确认案例',
                'include_cover': True,
                'inline_image_count': 1,
                'image_style': '极简',
            })
        self.assertEqual(async_result['job']['status'], 'succeeded')
        result = async_result['session']
        self.assertEqual(result['final_title'], '测试最终稿')
        self.assertEqual(len(result['images']), 2)

        for image in result['images']:
            response = self.client.post(
                f'/admin/ai-writing/sessions/{session_id}/images/{image["id"]}/generate',
                headers=self.headers,
                json={'prompt': image['prompt']},
            )
            self.assertEqual(response.status_code, 200, response.text)

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/apply', headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        applied = response.json()
        self.assertEqual(applied['title'], '测试最终稿')
        self.assertEqual(applied['missing_images'], 0)
        self.assertIn('![正文示意图](/uploads/', applied['content'])
        self.assertTrue(applied['cover_image'].startswith('/uploads/'))

        db = self.Session()
        stored = db.query(AIWritingSession).filter(AIWritingSession.id == session_id).one()
        self.assertEqual(stored.status, 'applied')
        db.close()
        self.assertEqual(self.fake_search.calls, [])

    def test_mutation_requires_valid_csrf(self):
        response = self.client.post('/admin/ai-writing/sessions', json={
            'topic': '测试主题',
            'core_points': '核心观点',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'CSRF token 无效')

    def test_research_is_explicit_selected_and_used_by_draft(self):
        response = self.client.post('/admin/ai-writing/sessions', headers=self.headers, json={
            'topic': '需要研究的主题',
            'core_points': '需要外部证据的观点',
        })
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()['id']

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/research/plan',
            headers=self.headers,
            json={'focus': '核实这个观点', 'current_content': ''},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['research_queries']), 2)
        self.assertEqual(response.json()['research_sources'], [])

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/research/search',
            headers=self.headers,
            json={'query': '官方技术文档', 'purpose': '核实技术结论'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        sources = response.json()['research_sources']
        self.assertEqual(len(sources), 2)
        self.assertFalse(any(source['selected'] for source in sources))

        response = self.client.patch(
            f'/admin/ai-writing/sessions/{session_id}/research/{sources[0]["id"]}',
            headers=self.headers,
            json={'selected': True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sum(source['selected'] for source in response.json()['research_sources']), 1)

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/draft',
            headers=self.headers,
            json={'current_content': ''},
        )
        self.assertEqual(response.status_code, 200, response.text)
        draft = response.json()
        self.assertIn('[可信来源](https://docs.example.com/guide)', draft['current_content'])
        self.assertNotIn('https://untrusted.example', draft['current_content'])
        self.assertEqual(draft['citation_warnings'], ['https://untrusted.example/article'])

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/interview',
            headers=self.headers,
            json={
                'user_message': '请根据资料回答这个问题。',
                'confirmed_brief': '',
                'current_content': draft['current_content'],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            '[资料](https://docs.example.com/guide)',
            response.json()['messages'][-1]['content'],
        )

        async_result = self.submit_and_run_finalize(session_id, {
                'current_content': draft['current_content'],
                'confirmed_brief': '',
                'include_cover': False,
                'inline_image_count': 0,
                'image_style': '极简',
            })
        final = async_result['session']
        self.assertIn('[最终稿可信引用](https://docs.example.com/guide)', final['final_content'])
        self.assertNotIn('https://untrusted.example/final', final['final_content'])

        response = self.client.patch(
            f'/admin/ai-writing/sessions/{session_id}/research/{sources[0]["id"]}',
            headers=self.headers,
            json={'selected': False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/apply', headers=self.headers
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('重新生成最终稿', response.json()['detail'])

    def test_image_plan_failure_keeps_final_article_usable(self):
        class FailingImagePlanWriter(FakeWriter):
            def plan_images(self, **kwargs):
                raise AIWriterError('配图规划超时')

        response = self.client.post('/admin/ai-writing/sessions', headers=self.headers, json={
            'topic': '容错测试',
            'core_points': '最终文章不应因配图规划失败而丢失',
        })
        session_id = response.json()['id']
        result = self.submit_and_run_finalize(
            session_id,
            {'current_content': '## 当前稿', 'confirmed_brief': ''},
            writer_factory=FailingImagePlanWriter,
        )
        self.assertEqual(result['job']['status'], 'partial')
        self.assertEqual(result['session']['status'], 'final_ready')
        self.assertEqual(result['session']['final_title'], '测试最终稿')
        self.assertTrue(result['session']['final_content'])
        self.assertIn('配图计划失败', result['session']['last_error'])

    def test_humanize_preserves_before_version_and_can_restore(self):
        response = self.client.post('/admin/ai-writing/sessions', headers=self.headers, json={
            'topic': '作者口吻测试',
            'core_points': '文章应该保留作者判断',
            'writing_mode': 'personal_opinion',
            'style_notes': '像和同行复盘，不要写成行业报告。',
        })
        session_id = response.json()['id']
        async_result = self.submit_and_run_finalize(session_id, {
                'current_content': '## 当前稿',
                'confirmed_brief': '- 作者有明确判断',
                'writing_mode': 'personal_opinion',
                'style_notes': '像和同行复盘，不要写成行业报告。',
                'include_cover': False,
                'inline_image_count': 0,
            })
        before = async_result['session']['final_content']

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/humanize', headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        humanized = response.json()
        self.assertEqual(humanized['status'], 'final_ready')
        self.assertEqual(humanized['pre_humanized_content'], before)
        self.assertEqual(humanized['final_title'], '更像作者的标题')
        self.assertIn('删除重复总结', humanized['humanize_summary'])
        self.assertNotEqual(humanized['final_content'], before)

        response = self.client.post(
            f'/admin/ai-writing/sessions/{session_id}/restore-humanize', headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        restored = response.json()
        self.assertEqual(restored['final_content'], before)
        self.assertEqual(restored['pre_humanized_content'], '')

    def test_actual_admin_page_renders_ai_studio(self):
        response = self.client.get('/admin/post/new')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('id="ai-writing-studio"', response.text)
        self.assertIn('data-max-inline-images="2"', response.text)
        self.assertIn('data-web-search-enabled="true"', response.text)

    def test_new_post_binds_persisted_ai_session(self):
        response = self.client.post('/admin/ai-writing/sessions', headers=self.headers, json={
            'topic': '需要保存的主题',
            'core_points': '作者观点',
        })
        session_id = response.json()['id']
        response = self.client.post('/admin/post/new', data={
            'title': '绑定会话的文章',
            'content': '## 正文',
            'status': '0',
            'cover_image': '',
            'ai_session_id': str(session_id),
            'csrf_token': self.csrf,
        })
        self.assertEqual(response.status_code, 200, response.text)
        db = self.Session()
        stored = db.query(AIWritingSession).filter(AIWritingSession.id == session_id).one()
        self.assertIsNotNone(stored.post_id)
        post_id = stored.post_id
        db.close()

        response = self.client.get(f'/admin/post/{post_id}/edit')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(f'data-session-id="{session_id}"', response.text)


if __name__ == '__main__':
    unittest.main()
