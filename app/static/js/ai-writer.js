(function () {
    'use strict';

    const STATUS_LABELS = {
        created: '准备生成初稿',
        planning_research: '正在规划检索词',
        searching: '正在搜索资料',
        research_ready: '研究资料待选择',
        generating_draft: '正在生成初稿',
        draft_ready: '初稿已生成',
        interviewing: '正在整理回答',
        interview_ready: '采访进行中',
        finalizing: '正在生成最终文章',
        planning_images: '正在规划配图',
        humanizing: '正在去除 AI 腔',
        final_ready: '最终稿待确认',
        applied: '已应用到编辑器',
        error: '生成遇到问题'
    };
    const JOB_PHASE_LABELS = {
        queued: '已进入后台队列',
        generating_article: '后台正在生成最终文章',
        article_ready: '最终文章已保存',
        planning_images: '后台正在规划配图',
        completed: '最终稿生成完成',
        completed_with_warning: '最终文章已完成，配图规划有警告',
        failed: '最终稿生成失败'
    };

    function initAIWriter(options) {
        const root = document.getElementById('ai-writing-studio');
        if (!root || !options || !options.editor) return;

        const editor = options.editor;
        const csrfToken = options.csrfToken;
        const postId = root.dataset.postId || null;
        const serverSessionId = root.dataset.sessionId || null;
        const textEnabled = root.dataset.textEnabled === 'true';
        const imageEnabled = root.dataset.imageEnabled === 'true';
        const webSearchEnabled = root.dataset.webSearchEnabled === 'true';
        const storageKey = `lightblog-ai-writing-${postId || 'new'}`;
        const stageStatePrefix = `lightblog-ai-stage-${postId || 'new'}-`;
        let session = null;
        let busy = false;
        let styleDirty = false;
        let monitoringJobId = null;

        const elements = {
            title: document.getElementById('post-title-input'),
            sessionId: document.getElementById('ai-session-id'),
            statusSelect: document.getElementById('post-status-input'),
            cover: document.getElementById('cover-image-input'),
            coverPreview: document.getElementById('cover-image-preview'),
            topic: document.getElementById('ai-topic'),
            corePoints: document.getElementById('ai-core-points'),
            audience: document.getElementById('ai-audience'),
            length: document.getElementById('ai-length'),
            writingMode: document.getElementById('ai-writing-mode'),
            styleNotes: document.getElementById('ai-style-notes'),
            status: document.getElementById('ai-session-status'),
            error: document.getElementById('ai-error'),
            messages: document.getElementById('ai-messages'),
            userMessage: document.getElementById('ai-user-message'),
            confirmedBrief: document.getElementById('ai-confirmed-brief'),
            generateDraft: document.getElementById('ai-generate-draft'),
            ask: document.getElementById('ai-ask'),
            send: document.getElementById('ai-send'),
            finalize: document.getElementById('ai-finalize'),
            includeCover: document.getElementById('ai-include-cover'),
            imageCount: document.getElementById('ai-inline-image-count'),
            imageStyle: document.getElementById('ai-image-style'),
            researchQuery: document.getElementById('ai-research-query'),
            planResearch: document.getElementById('ai-plan-research'),
            verifySelection: document.getElementById('ai-verify-selection'),
            search: document.getElementById('ai-search'),
            researchQueries: document.getElementById('ai-research-queries'),
            researchSources: document.getElementById('ai-research-sources'),
            sourceCount: document.getElementById('ai-source-count'),
            reanswer: document.getElementById('ai-reanswer'),
            finalResult: document.getElementById('ai-final-result'),
            finalContent: document.getElementById('ai-final-content'),
            citationWarning: document.getElementById('ai-citation-warning'),
            humanize: document.getElementById('ai-humanize'),
            restoreHumanize: document.getElementById('ai-restore-humanize'),
            humanizeDiff: document.getElementById('ai-humanize-diff'),
            humanizeSummary: document.getElementById('ai-humanize-summary'),
            humanizeBefore: document.getElementById('ai-humanize-before'),
            humanizeAfter: document.getElementById('ai-humanize-after'),
            imageList: document.getElementById('ai-image-list'),
            replanImages: document.getElementById('ai-replan-images'),
            generateAll: document.getElementById('ai-generate-all-images'),
            applyFinal: document.getElementById('ai-apply-final')
        };

        function showError(message) {
            elements.error.textContent = message || '操作失败，请稍后重试。';
            elements.error.hidden = false;
        }

        function clearError() {
            elements.error.textContent = '';
            elements.error.hidden = true;
        }

        async function api(path, method, payload) {
            const response = await fetch(`/admin/ai-writing${path}`, {
                method: method || 'GET',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: payload === undefined ? undefined : JSON.stringify(payload)
            });
            let data = {};
            try {
                data = await response.json();
            } catch (_) {
                data = {};
            }
            if (!response.ok) {
                throw new Error(data.detail || `请求失败（${response.status}）`);
            }
            return data;
        }

        function setBusy(value, label) {
            busy = value;
            root.classList.toggle('is-busy', value);
            root.querySelectorAll('button').forEach(function (button) {
                if (button === elements.generateDraft && !textEnabled) return;
                button.disabled = value || button.dataset.available === 'false';
            });
            if (value && label) {
                elements.status.textContent = label;
                elements.status.dataset.state = 'busy';
            } else {
                updateControls();
            }
        }

        function updateControls() {
            const hasDraft = Boolean(session && session.current_content);
            const hasFinal = Boolean(session && session.final_content);
            const finalIsCurrent = Boolean(session && ['final_ready', 'applied'].includes(session.status));
            elements.generateDraft.disabled = busy || !textEnabled;
            elements.ask.disabled = busy || !textEnabled || !hasDraft;
            elements.send.disabled = busy || !textEnabled || !hasDraft || !elements.userMessage.value.trim();
            elements.finalize.disabled = busy || !textEnabled || !hasDraft;
            elements.planResearch.disabled = busy || !textEnabled;
            elements.verifySelection.disabled = busy || !textEnabled;
            elements.search.disabled = busy || !textEnabled;
            const selectedSourceCount = session
                ? (session.research_sources || []).filter(function (source) { return source.selected; }).length
                : 0;
            const hasQuestion = Boolean(elements.userMessage.value.trim()) || Boolean(session && session.messages.some(function (message) {
                return message.role === 'user';
            }));
            elements.reanswer.disabled = busy || !textEnabled || !selectedSourceCount || !hasQuestion;
            elements.humanize.disabled = busy || !textEnabled || !hasFinal;
            elements.restoreHumanize.disabled = busy || !hasFinal || !session.pre_humanized_content;
            elements.replanImages.disabled = busy || !textEnabled || !hasFinal;
            elements.generateAll.disabled = busy || !imageEnabled || !hasFinal || !finalIsCurrent || !session.images.some(function (image) {
                return image.status !== 'ready';
            });
            elements.applyFinal.disabled = busy || !hasFinal || !finalIsCurrent;
            root.querySelectorAll('.ai-source-item input[type="checkbox"]').forEach(function (checkbox) {
                checkbox.disabled = busy;
            });
        }

        function ensureWebSearchConfigured() {
            if (webSearchEnabled) return true;
            window.alert('网络搜索未配置。请在服务器环境变量中设置 WEB_SEARCH_PROVIDER、WEB_SEARCH_API_BASE 和 WEB_SEARCH_API_KEY，然后重启服务。');
            return false;
        }

        function openStage(name) {
            const stage = root.querySelector(`[data-ai-stage="${name}"]`);
            if (!stage) return;
            stage.open = true;
            localStorage.setItem(`${stageStatePrefix}${name}`, 'true');
        }

        function latestConversationFocus() {
            const manual = elements.researchQuery.value.trim();
            if (manual) return manual;
            const pendingQuestion = elements.userMessage.value.trim();
            if (pendingQuestion) return pendingQuestion;
            if (!session) return '';
            const recent = (session.messages || []).filter(function (message) {
                return message.message_type !== 'draft' && message.message_type !== 'research_plan';
            }).slice(-2);
            return recent.map(function (message) {
                return `${message.role === 'user' ? '用户问题' : '模型回答'}：${message.content}`;
            }).join('\n');
        }

        function renderResearchQueries(queries) {
            elements.researchQueries.replaceChildren();
            elements.researchQueries.hidden = !queries.length;
            queries.forEach(function (item) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'ai-query-chip';
                button.textContent = item.query;
                button.title = item.purpose || '使用这个检索词';
                button.disabled = busy;
                button.addEventListener('click', function () {
                    elements.researchQuery.value = item.query;
                    elements.researchQuery.dataset.purpose = item.purpose || '';
                    updateControls();
                });
                elements.researchQueries.appendChild(button);
            });
        }

        function renderResearchSources(sources) {
            elements.researchSources.replaceChildren();
            const selectedCount = sources.filter(function (source) { return source.selected; }).length;
            elements.sourceCount.textContent = `已选 ${selectedCount} 条`;
            if (!sources.length) {
                const empty = document.createElement('div');
                empty.className = 'ai-empty-state';
                empty.textContent = '还没有搜索资料。你也可以跳过这一步，直接生成初稿。';
                elements.researchSources.appendChild(empty);
                return;
            }
            sources.forEach(function (source) {
                const item = document.createElement('article');
                item.className = `ai-source-item${source.selected ? ' is-selected' : ''}`;

                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.checked = source.selected;
                checkbox.disabled = busy;
                checkbox.setAttribute('aria-label', `选择来源：${source.title}`);
                checkbox.addEventListener('change', function () {
                    selectSource(source.id, checkbox.checked);
                });

                const body = document.createElement('div');
                body.className = 'ai-source-body';
                const title = document.createElement('a');
                title.href = source.url;
                title.target = '_blank';
                title.rel = 'noopener noreferrer';
                title.textContent = source.title;
                const meta = document.createElement('div');
                meta.className = 'ai-source-meta';
                const parts = [source.source_name];
                if (source.published_at) parts.push(source.published_at);
                if (source.purpose) parts.push(`用于：${source.purpose}`);
                meta.textContent = parts.filter(Boolean).join(' | ');
                const snippet = document.createElement('p');
                snippet.textContent = source.snippet || '搜索服务未提供摘要，请打开原文核对。';
                body.append(title, meta, snippet);
                item.append(checkbox, body);
                elements.researchSources.appendChild(item);
            });
        }

        function renderMessage(message) {
            const item = document.createElement('article');
            item.className = `ai-message ai-message-${message.role}`;
            const label = document.createElement('div');
            label.className = 'ai-message-role';
            label.textContent = message.role === 'user' ? '你' : 'AI 编辑';
            const content = document.createElement('div');
            content.className = 'ai-message-content';
            content.textContent = message.content;
            item.append(label, content);
            return item;
        }

        function renderImages(images) {
            elements.imageList.replaceChildren();
            if (!images.length) {
                const empty = document.createElement('p');
                empty.className = 'ai-empty-state';
                empty.textContent = '这次最终稿没有规划配图。';
                elements.imageList.appendChild(empty);
                return;
            }
            const finalIsCurrent = Boolean(session && ['final_ready', 'applied'].includes(session.status));
            images.forEach(function (image) {
                const card = document.createElement('article');
                card.className = 'ai-image-card';
                card.dataset.imageId = String(image.id);

                const preview = document.createElement('div');
                preview.className = 'ai-image-preview';
                if (image.url) {
                    const img = document.createElement('img');
                    img.src = image.url;
                    img.alt = image.alt || '文章配图预览';
                    preview.appendChild(img);
                } else {
                    preview.textContent = image.type === 'cover' ? '封面待生成' : '正文配图待生成';
                }

                const body = document.createElement('div');
                body.className = 'ai-image-body';
                const heading = document.createElement('div');
                heading.className = 'ai-image-heading';
                const title = document.createElement('strong');
                title.textContent = image.type === 'cover' ? '文章封面' : (image.after_heading || image.slot);
                const state = document.createElement('span');
                state.className = `ai-image-state ai-image-state-${image.status}`;
                state.textContent = image.status === 'ready' ? '已生成' : image.status === 'failed' ? '生成失败' : '待生成';
                heading.append(title, state);

                const prompt = document.createElement('textarea');
                prompt.className = 'ai-image-prompt';
                prompt.rows = 3;
                prompt.maxLength = 4000;
                prompt.value = image.prompt;
                prompt.setAttribute('aria-label', `${title.textContent}提示词`);

                const actions = document.createElement('div');
                actions.className = 'ai-image-actions';
                const alt = document.createElement('span');
                alt.textContent = `替代文本：${image.alt || '文章配图'}`;
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-sm';
                button.textContent = image.status === 'ready' ? '重新生成' : '生成图片';
                button.dataset.available = imageEnabled && finalIsCurrent ? 'true' : 'false';
                button.disabled = busy || !imageEnabled || !finalIsCurrent;
                button.addEventListener('click', function () {
                    generateOneImage(image.id, prompt.value);
                });
                actions.append(alt, button);
                if (image.error) {
                    const error = document.createElement('p');
                    error.className = 'ai-image-error';
                    error.textContent = image.error;
                    body.append(heading, prompt, actions, error);
                } else {
                    body.append(heading, prompt, actions);
                }
                card.append(preview, body);
                elements.imageList.appendChild(card);
            });
        }

        function renderSession(nextSession) {
            session = nextSession;
            localStorage.setItem(storageKey, String(session.id));
            elements.sessionId.value = String(session.id);
            elements.status.textContent = STATUS_LABELS[session.status] || session.status;
            elements.status.dataset.state = session.status === 'error' ? 'error' : session.status;
            elements.topic.value = session.topic || elements.topic.value;
            elements.corePoints.value = session.core_points || elements.corePoints.value;
            elements.audience.value = session.target_audience || elements.audience.value;
            elements.confirmedBrief.value = session.confirmed_brief || '';
            if (!styleDirty) {
                elements.writingMode.value = session.writing_mode || 'personal_opinion';
                elements.styleNotes.value = session.style_notes || '';
            }
            renderResearchQueries(session.research_queries || []);
            renderResearchSources(session.research_sources || []);

            elements.messages.replaceChildren();
            if (session.messages.length) {
                session.messages.forEach(function (message) {
                    elements.messages.appendChild(renderMessage(message));
                });
            } else {
                const empty = document.createElement('div');
                empty.className = 'ai-empty-state';
                empty.textContent = '初稿生成后，这里会保留你与 AI 编辑的讨论。';
                elements.messages.appendChild(empty);
            }

            const hasFinal = Boolean(session.final_content);
            elements.finalResult.hidden = !hasFinal;
            if (hasFinal) {
                elements.finalContent.textContent = session.assembled_content || session.final_content;
                const warnings = session.citation_warnings || [];
                const finalIsCurrent = ['final_ready', 'applied'].includes(session.status);
                const warningParts = [];
                if (!finalIsCurrent) warningParts.push('研究资料或访谈内容已更新，请重新生成最终稿。');
                if (warnings.length) {
                    warningParts.push(`已移除 ${warnings.length} 个未选来源链接，请核对“引用待核实”标记。`);
                }
                elements.citationWarning.hidden = !warningParts.length;
                elements.citationWarning.textContent = warningParts.join(' ');
                renderImages(session.images || []);
            }
            const hasHumanizedVersion = Boolean(session.pre_humanized_content);
            elements.humanizeDiff.hidden = !hasHumanizedVersion;
            if (hasHumanizedVersion) {
                elements.humanizeSummary.textContent = session.humanize_summary || '已完成表达优化。';
                elements.humanizeBefore.textContent = session.pre_humanized_content;
                elements.humanizeAfter.textContent = session.final_content;
            }
            if (session.last_error) showError(session.last_error);
            updateControls();
            if (session.active_job && !monitoringJobId) {
                window.setTimeout(function () {
                    resumeFinalizeJob(session.active_job);
                }, 0);
            }
        }

        async function ensureSession() {
            const topic = elements.topic.value.trim();
            const corePoints = elements.corePoints.value.trim();
            if (!topic || !corePoints) {
                throw new Error('请先填写主题和核心观点。');
            }
            if (session && session.topic === topic && session.core_points === corePoints) {
                return session;
            }
            const next = await api('/sessions', 'POST', {
                post_id: postId ? Number(postId) : null,
                topic: topic,
                core_points: corePoints,
                target_audience: elements.audience.value.trim(),
                desired_length: elements.length.value,
                writing_mode: elements.writingMode.value,
                style_notes: elements.styleNotes.value.trim(),
                source_content: editor.value()
            });
            renderSession(next);
            return next;
        }

        async function startDraft() {
            clearError();
            setBusy(true, '正在建立写作会话');
            try {
                await ensureSession();
                elements.status.textContent = '正在生成初稿';
                const next = await api(`/sessions/${session.id}/draft`, 'POST', {
                    current_content: editor.value(),
                    writing_mode: elements.writingMode.value,
                    style_notes: elements.styleNotes.value.trim()
                });
                styleDirty = false;
                renderSession(next);
                if (next.draft_title) elements.title.value = next.draft_title;
                editor.value(next.current_content);
                openStage('interview');
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function planResearch(focus, searchFirstQuery) {
            if (searchFirstQuery && !ensureWebSearchConfigured()) return;
            clearError();
            setBusy(true, '正在规划检索词');
            try {
                await ensureSession();
                const next = await api(`/sessions/${session.id}/research/plan`, 'POST', {
                    focus: focus || '',
                    current_content: editor.value()
                });
                renderSession(next);
                if (next.research_queries.length) {
                    elements.researchQuery.value = next.research_queries[0].query;
                    elements.researchQuery.dataset.purpose = next.research_queries[0].purpose || '';
                    if (searchFirstQuery) {
                        elements.status.textContent = '正在搜索选中文字的资料';
                        const searched = await api(`/sessions/${session.id}/research/search`, 'POST', {
                            query: next.research_queries[0].query,
                            purpose: next.research_queries[0].purpose || ''
                        });
                        renderSession(searched);
                    }
                }
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function selectSource(sourceId, selected) {
            if (!session) return;
            clearError();
            setBusy(true, selected ? '正在加入资料' : '正在移除资料');
            try {
                const next = await api(`/sessions/${session.id}/research/${sourceId}`, 'PATCH', { selected });
                renderSession(next);
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function runInterview(withMessage, overrideMessage) {
            if (!session) return;
            const message = overrideMessage !== undefined
                ? overrideMessage
                : (withMessage ? elements.userMessage.value.trim() : '');
            if (withMessage && !message) return;
            clearError();
            setBusy(true, withMessage ? '正在整理你的回答' : '正在准备采访问题');
            try {
                const next = await api(`/sessions/${session.id}/interview`, 'POST', {
                    user_message: message,
                    confirmed_brief: elements.confirmedBrief.value.trim(),
                    current_content: editor.value()
                });
                elements.userMessage.value = '';
                renderSession(next);
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        function reanswerWithSelectedSources() {
            if (!session) return;
            const selectedCount = (session.research_sources || []).filter(function (source) {
                return source.selected;
            }).length;
            if (!selectedCount) {
                window.alert('请先在搜索结果中勾选至少一条资料。');
                return;
            }
            const pendingQuestion = elements.userMessage.value.trim();
            const lastUserMessage = (session.messages || []).slice().reverse().find(function (message) {
                return message.role === 'user';
            });
            const question = pendingQuestion || (lastUserMessage ? lastUserMessage.content : '');
            if (!question) {
                window.alert('没有找到需要重新回答的问题，请先在采访输入框中填写问题。');
                return;
            }
            runInterview(
                true,
                `请基于我刚刚选择的资料重新回答这个问题，并明确指出原回答需要修正的地方：\n${question}`
            );
        }

        async function finalizeArticle() {
            if (!session) return;
            clearError();
            setBusy(true, '正在生成最终文章');
            try {
                const submitted = await api(`/sessions/${session.id}/finalize`, 'POST', {
                    current_content: editor.value(),
                    confirmed_brief: elements.confirmedBrief.value.trim(),
                    writing_mode: elements.writingMode.value,
                    style_notes: elements.styleNotes.value.trim(),
                    include_cover: elements.includeCover.checked,
                    inline_image_count: Number(elements.imageCount.value),
                    image_style: elements.imageStyle.value
                });
                styleDirty = false;
                await monitorFinalizeJob(submitted.job.id);
            } catch (error) {
                showError(error.message);
            } finally {
                if (!monitoringJobId) setBusy(false);
            }
        }

        function wait(milliseconds) {
            return new Promise(function (resolve) {
                window.setTimeout(resolve, milliseconds);
            });
        }

        function updateJobProgress(job) {
            const label = JOB_PHASE_LABELS[job.phase] || '后台生成中';
            elements.status.textContent = `${label} ${job.progress}%`;
            elements.status.dataset.state = 'busy';
        }

        async function monitorFinalizeJob(jobId) {
            monitoringJobId = jobId;
            try {
                while (monitoringJobId === jobId) {
                    const result = await api(`/jobs/${jobId}`, 'GET');
                    const job = result.job;
                    updateJobProgress(job);
                    if (['succeeded', 'partial', 'failed'].includes(job.status)) {
                        if (result.session) renderSession(result.session);
                        if (job.status === 'partial') showError(job.error);
                        if (job.status === 'failed') showError(job.error || '最终稿生成失败，请重新提交。');
                        if (job.status !== 'failed') {
                            openStage('final');
                            elements.finalResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        }
                        break;
                    }
                    await wait(1500);
                }
            } catch (error) {
                showError(`无法读取后台任务进度，任务仍会继续运行。刷新页面可恢复：${error.message}`);
            } finally {
                if (monitoringJobId === jobId) monitoringJobId = null;
                setBusy(false);
            }
        }

        function resumeFinalizeJob(job) {
            if (!job || monitoringJobId || ['succeeded', 'partial', 'failed'].includes(job.status)) return;
            setBusy(true, JOB_PHASE_LABELS[job.phase] || '正在恢复后台任务进度');
            monitorFinalizeJob(job.id);
        }

        function requestImagePlan() {
            return api(`/sessions/${session.id}/plan-images`, 'POST', {
                include_cover: elements.includeCover.checked,
                inline_image_count: Number(elements.imageCount.value),
                image_style: elements.imageStyle.value
            });
        }

        async function replanImages() {
            if (!session || !session.final_content) return;
            clearError();
            setBusy(true, '正在重新规划配图');
            try {
                const next = await requestImagePlan();
                renderSession(next);
            } catch (error) {
                showError(`最终稿保持不变，配图计划失败：${error.message}`);
            } finally {
                setBusy(false);
            }
        }

        async function humanizeFinal() {
            if (!session || !session.final_content) return;
            clearError();
            setBusy(true, '正在去除 AI 腔');
            try {
                const next = await api(`/sessions/${session.id}/humanize`, 'POST');
                renderSession(next);
                elements.humanizeDiff.open = true;
                elements.humanizeDiff.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function restoreHumanizedVersion() {
            if (!session || !session.pre_humanized_content) return;
            clearError();
            setBusy(true, '正在恢复润色前版本');
            try {
                const next = await api(`/sessions/${session.id}/restore-humanize`, 'POST');
                renderSession(next);
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function generateOneImage(imageId, prompt, keepBusy) {
            if (!session) return;
            clearError();
            if (!keepBusy) setBusy(true, '正在生成配图');
            try {
                const next = await api(`/sessions/${session.id}/images/${imageId}/generate`, 'POST', {
                    prompt: prompt || ''
                });
                renderSession(next);
                return next;
            } catch (error) {
                showError(error.message);
                throw error;
            } finally {
                if (!keepBusy) setBusy(false);
            }
        }

        async function generateAllImages() {
            if (!session || !imageEnabled) return;
            const pendingIds = new Set(session.images.filter(function (image) {
                return image.status !== 'ready';
            }).map(function (image) {
                return image.id;
            }));
            const jobs = Array.from(elements.imageList.querySelectorAll('.ai-image-card')).filter(function (card) {
                return pendingIds.has(Number(card.dataset.imageId));
            }).map(function (card) {
                return {
                    id: Number(card.dataset.imageId),
                    prompt: card.querySelector('.ai-image-prompt').value
                };
            });
            if (!jobs.length) return;
            clearError();
            setBusy(true, `正在生成配图 1/${jobs.length}`);
            try {
                for (let index = 0; index < jobs.length; index += 1) {
                    elements.status.textContent = `正在生成配图 ${index + 1}/${jobs.length}`;
                    await generateOneImage(jobs[index].id, jobs[index].prompt, true);
                }
            } catch (_) {
                // generateOneImage already renders the actionable provider error.
            } finally {
                setBusy(false);
            }
        }

        async function applyFinal() {
            if (!session) return;
            const missing = session.images.filter(function (image) { return image.status !== 'ready'; }).length;
            if (missing && !window.confirm(`还有 ${missing} 张配图未生成。继续后会移除这些占位符，是否应用？`)) {
                return;
            }
            clearError();
            setBusy(true, '正在应用最终稿');
            try {
                const result = await api(`/sessions/${session.id}/apply`, 'POST');
                elements.title.value = result.title;
                editor.value(result.content);
                elements.cover.value = result.cover_image || '';
                elements.cover.dispatchEvent(new Event('input', { bubbles: true }));
                elements.statusSelect.value = '0';
                session.status = 'applied';
                session.current_content = result.content;
                renderSession(session);
                elements.status.textContent = '已应用，请保存草稿';
                document.getElementById('content-editor').closest('.form-group').scrollIntoView({
                    behavior: 'smooth', block: 'start'
                });
            } catch (error) {
                showError(error.message);
            } finally {
                setBusy(false);
            }
        }

        async function restoreSession() {
            const savedId = serverSessionId || localStorage.getItem(storageKey);
            if (!savedId) return;
            try {
                const restored = await api(`/sessions/${savedId}`, 'GET');
                if (postId && String(restored.post_id || '') !== String(postId)) {
                    localStorage.removeItem(storageKey);
                    return;
                }
                if (!postId && restored.post_id !== null) {
                    localStorage.removeItem(storageKey);
                    return;
                }
                renderSession(restored);
            } catch (_) {
                localStorage.removeItem(storageKey);
            }
        }

        elements.generateDraft.addEventListener('click', startDraft);
        elements.ask.addEventListener('click', function () { runInterview(false); });
        elements.send.addEventListener('click', function () { runInterview(true); });
        elements.userMessage.addEventListener('input', updateControls);
        elements.writingMode.addEventListener('change', function () { styleDirty = true; });
        elements.styleNotes.addEventListener('input', function () { styleDirty = true; });
        elements.confirmedBrief.addEventListener('input', function () {
            if (session && session.final_content && session.status === 'final_ready') {
                session.status = 'interview_ready';
                elements.status.textContent = '确认要点已修改，请重新生成最终稿';
                elements.status.dataset.state = 'interview_ready';
            }
            updateControls();
        });
        elements.researchQuery.addEventListener('input', function () {
            elements.researchQuery.dataset.purpose = '';
            updateControls();
        });
        elements.planResearch.addEventListener('click', function () { planResearch('', false); });
        elements.verifySelection.addEventListener('click', function () {
            if (!ensureWebSearchConfigured()) return;
            const selected = editor.codemirror.getSelection().trim();
            if (!selected) {
                showError('请先在 Markdown 编辑器中选中需要核实的文字。');
                return;
            }
            elements.researchQuery.value = selected;
            planResearch(selected, true);
        });
        elements.search.addEventListener('click', function () {
            if (!ensureWebSearchConfigured()) return;
            const focus = latestConversationFocus();
            if (!focus) {
                showError('请先填写主题、核心观点或需要核实的问题。');
                return;
            }
            planResearch(focus, true);
        });
        elements.reanswer.addEventListener('click', reanswerWithSelectedSources);
        elements.finalize.addEventListener('click', finalizeArticle);
        elements.humanize.addEventListener('click', humanizeFinal);
        elements.restoreHumanize.addEventListener('click', restoreHumanizedVersion);
        elements.replanImages.addEventListener('click', replanImages);
        elements.generateAll.addEventListener('click', generateAllImages);
        elements.applyFinal.addEventListener('click', applyFinal);
        editor.codemirror.on('change', function () {
            if (!busy && session && session.final_content && session.status === 'final_ready') {
                session.status = 'interview_ready';
                elements.status.textContent = '正文已修改，请重新生成最终稿';
                elements.status.dataset.state = 'interview_ready';
                updateControls();
            }
        });

        if (!imageEnabled) {
            elements.generateAll.title = '请先配置 AI_IMAGE_MODEL';
        }
        root.querySelectorAll('[data-ai-stage]').forEach(function (stage) {
            const name = stage.dataset.aiStage;
            const savedState = localStorage.getItem(`${stageStatePrefix}${name}`);
            if (savedState === 'false') stage.removeAttribute('open');
            if (savedState === 'true') stage.setAttribute('open', '');
            stage.addEventListener('toggle', function () {
                localStorage.setItem(`${stageStatePrefix}${name}`, stage.open ? 'true' : 'false');
            });
        });
        updateControls();
        restoreSession();
    }

    window.initAIWriter = initAIWriter;
}());
