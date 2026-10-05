# AI 共创写作 MVP

## 功能边界

AI 共创嵌入现有文章编辑页，支持：

1. 根据主题、核心观点、读者和篇幅生成 Markdown 初稿。
2. 支持个人判断、技术教程、问题复盘、观点辩论和研究笔记五种表达方式，并保存作者口吻要求。
3. AI 围绕真实经历、证据、反例和适用边界采访作者。
4. 按需规划检索词、执行 Web Search，并由作者选择可信来源。
5. 将回答压缩为作者可编辑的“已确认写作要点”。
6. 综合当前稿、确认要点、最近对话和已选资料生成并立即保存最终候选稿。
7. 可独立执行“去除 AI 腔”编辑，保存润色前版本、修改摘要和前后正文，并支持恢复。
8. 通过独立请求规划一张封面和有限数量的正文概念插画，逐张调用外部图片模型；规划失败不影响最终文章。
9. 将图片压缩为 WebP 并保存到 `/uploads/YYYY/MM/`，自动插入 Markdown。
10. 将候选稿应用到编辑器并切换为草稿；不会自动保存或发布。

MVP 不包含无限制网页爬取、向量库、本地模型、定时自动发布和技术架构图渲染。图片模型只用于概念插画；包含复杂文字的技术图应由后续 Mermaid 功能完成。

## 状态与持久化

- `ai_writing_session`：主题、初稿、当前稿、最终稿、确认要点和状态。
- `ai_writing_message`：作者与 AI 编辑的最近对话。
- `ai_writing_image`：配图位置、提示词、替代文本、生成状态和本地路径。
- `ai_research_source`：搜索问题、来源 URL、证据摘要、选择状态和内容摘要。
- `ai_writing_job`：最终稿后台任务、阶段进度、重试次数和错误状态。

写作会话还保存 `writing_mode`、`style_notes`、`pre_humanized_content` 和 `humanize_summary`，用于稳定作者口吻和可恢复的表达编辑。

会话状态保存在 SQLite，不依赖 Gunicorn worker 内存。生成前通过条件更新领取会话或图片任务，避免重复点击造成并发调用。

模型调用前先提交数据库事务，外部网络等待期间不持有 SQLite 写事务。最终生成只发送当前文章、确认要点和最近八条消息，避免历史对话无限膨胀。

## 最终稿异步任务

`POST /admin/ai-writing/sessions/{id}/finalize` 只负责校验输入和写入任务，立即返回 HTTP 202 与 `job_id`。后台 worker 使用 SQLite 条件更新原子领取任务：

```text
queued -> generating_article -> article_ready -> planning_images -> completed
```

- 文章生成成功后立即写入会话，进度更新为 70%。
- 配图规划失败时任务为 `partial`，文章保持 `final_ready`。
- 页面通过 `GET /admin/ai-writing/jobs/{job_id}` 轮询进度。
- 刷新页面后，会话响应中的 `active_job` 用于恢复轮询。
- worker 重启会回收超过 `AI_JOB_STALE_SECONDS` 的任务；已有文章的任务从配图阶段继续。
- 多进程部署中每个 Web worker 可以启动一个轻量任务线程，但同一任务只能被一个进程领取。

## 按需网络搜索

Web Search 不使用文本模型的原生搜索能力，必须显式配置标准 Tavily 或 Tavily Hub。标准 Tavily 配置：

```dotenv
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_BASE=https://api.tavily.com
WEB_SEARCH_API_KEY=your-tavily-key
```

若使用 Tavily Hub Bearer 代理：

```dotenv
WEB_SEARCH_PROVIDER=tavily_hub
WEB_SEARCH_API_BASE=https://tavily.sharyuke.com/api/proxy
WEB_SEARCH_API_KEY=your-hub-key
```

网络搜索只在用户点击“搜索资料”或“核实选中文字”后执行。普通采访问答和最终生成不会隐式发起搜索。每轮最多规划三个检索词、每次最多保留五条结果；相同会话中的 URL 会去重更新。

搜索结果默认不参与写作。作者勾选来源后，服务才会把最多八条资料放入初稿或最终稿上下文。网页内容被明确标记为不可信证据，不能改变系统提示；URL 只允许公开 HTTP(S) 地址，并拒绝 localhost、私网、链路本地和保留地址。

生成后会校验所有 Markdown 外部链接：仅保留作者选中来源中的 URL，其余链接转换为“引用待核实”文字并在界面提示。

## Provider 合约

文本接口：

```text
POST {AI_API_BASE}/chat/completions
Authorization: Bearer {AI_API_KEY}
```

响应应兼容：

```json
{"choices":[{"message":{"content":"{...JSON...}"}}]}
```

图片接口：

```text
POST {AI_API_BASE}/images/generations
Authorization: Bearer {AI_API_KEY}
```

图片响应支持 `data[0].b64_json` 或 `data[0].url`。下载内容最大 20MB，解码后最大 4000 万像素，最长边压缩至 1600 像素并保存为 WebP。

## 错误处理

- 未配置模型时接口返回 503，并在后台显示具体配置项。
- Provider 超时、HTTP 错误或 JSON 不兼容时返回 502，会话保留为 `error`，可以直接重试。
- 最终文章生成和配图规划是两个独立模型请求；文章成功后立即落库。配图规划失败时会话恢复为 `final_ready`，保留文章并允许单独重试。
- 每张配图独立生成。单张失败不会删除文章和其他已完成图片。
- 应用最终稿时，未生成图片的占位符会被移除，已生成图片按本地 URL 插入。
- 普通文章编辑、图片上传和发布流程不依赖 AI Provider，模型故障时仍可使用。
