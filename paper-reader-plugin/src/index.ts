/**
 * Paper Reader plugin - host side.
 *
 * Registers three tools:
 * - paper_load: ingest paper text or extract from a local file path
 * - paper_translate: translate the loaded paper into Chinese
 * - paper_qa: answer a question grounded in the loaded paper
 *
 * Also serves two HTTP endpoints for the client UI:
 * - GET /paper-reader/files?path=<path> - list files in a directory
 * - GET /paper-reader/read?path=<path> - read a file's content
 *
 * Each tool appends a paper/* session event. A projection folds those events
 * into a `paperReader` state that the client UI reads via
 * `session.projections.faceOf('paperReader')`.
 */
import type { Context } from '@deepseek-ai/cordis'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { defineTool } from '@deepseek-ai/dsh-tools'
import {
  BlockAssembler,
  createUserMessage,
  deepFreeze,
  type GenerateOptions,
  type Message,
} from '@deepseek-ai/dsh-llm'
import { readFile, readdir, stat } from 'node:fs/promises'
import { isAbsolute, join, relative, resolve } from 'node:path'
import { z } from 'zod'
import type { ProjectionDefinition } from '@deepseek-ai/dsh-session-projection'

export const name = 'paper-reader'
export const inject = ['tools', 'llm', 'sessionProjections', 'webServer']

/** In-memory paper store keyed by agent id. */
const papers = new Map<string, string>()

/** Session event vocabulary owned by this plugin. */
declare module '@deepseek-ai/dsh-session/types' {
  interface SessionEventMap {
    'paper/loaded': { chars: number; preview: string }
    'paper/translated': { translation: string }
    'paper/answered': { question: string; answer: string }
  }
}

/** Projection state for the paper reader. */
interface PaperReaderState {
  loaded: boolean
  chars: number
  preview: string
  translation: string
  qa: Array<{ question: string; answer: string }>
}

declare module '@deepseek-ai/dsh-session-projection/types' {
  interface SessionProjectionStateMap {
    paperReader: PaperReaderState
  }
  interface SessionProjectionMap {
    paperReader: PaperReaderState
  }
}

const paperReaderStateSchema = z.object({
  loaded: z.boolean(),
  chars: z.number().int().nonnegative(),
  preview: z.string(),
  translation: z.string(),
  qa: z.array(z.object({ question: z.string(), answer: z.string() })),
}).strict()

const paperReaderProjection: ProjectionDefinition<'paperReader', PaperReaderState> = {
  key: 'paperReader',
  stateSchema: paperReaderStateSchema,
  stateVersion: 1,
  init: () => ({ loaded: false, chars: 0, preview: '', translation: '', qa: [] }),
  apply(state, event) {
    switch (event.type) {
      case 'paper/loaded':
        return { ...state, loaded: true, chars: event.data.chars, preview: event.data.preview }
      case 'paper/translated':
        return { ...state, translation: event.data.translation }
      case 'paper/answered':
        return { ...state, qa: [...state.qa, { question: event.data.question, answer: event.data.answer }] }
      default:
        return state
    }
  },
  wire: {
    viewSchema: paperReaderStateSchema,
    view: (state) => state,
  },
}

/**
 * Call the agent's LLM with a single user message and return the text output.
 */
async function llmText(
  ctx: Context,
  exec: {
    agent: {
      options: { provider?: string; model?: string }
      id: string
      session: { append: (type: string, data: unknown) => void }
    }
    signal: AbortSignal
  },
  system: string,
  userText: string,
): Promise<string> {
  const provider = exec.agent.options.provider
  const model = exec.agent.options.model
  if (!provider || !model) {
    throw new Error('paper-reader: no provider/model selected for this agent')
  }
  const messages: Message[] = [createUserMessage({
    content: [{ type: 'text', text: userText }],
    source: { kind: 'plugin', plugin: 'paper-reader' },
  })]
  const options: GenerateOptions = deepFreeze({
    provider,
    model,
    messages,
    system,
    maxTokens: 4096,
    sessionId: exec.agent.id,
    purpose: 'paper-reader',
    signal: exec.signal,
  })
  const assembler = new BlockAssembler()
  for await (const chunk of ctx.llm.stream(options)) {
    assembler.push(chunk)
  }
  const blocks = assembler.blocks()
  return blocks
    .filter((b): b is Extract<(typeof blocks)[number], { type: 'text' }> => b.type === 'text')
    .map((b) => b.text)
    .join('')
}

export function apply(ctx: Context): void {
  // Register the projection so the client can read paper state.
  ctx.sessionProjections.register(paperReaderProjection)

  // --- HTTP routes for client-side file browsing --------------------------

  /**
   * Resolve a relative path to an absolute path under the allowed base.
   * Uses cwd as the base directory. Path traversal is rejected.
   */
  const allowedDir = process.cwd()
  function resolvePath(raw: string): string {
    const decoded = decodeURIComponent(raw)
    const normalized = isAbsolute(decoded)
      ? resolve(decoded)
      : resolve(allowedDir, decoded)

    if (!normalized.startsWith(allowedDir)) {
      throw new Error('Path traversal denied')
    }
    return normalized
  }

  /** Serve GET /paper-reader/files?path=<path> - list directory contents. */
  async function serveFiles(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      res.writeHead(405)
      res.end()
      return
    }
    try {
      const url = new URL(req.url ?? '/', 'http://x')
      const rawPath = url.searchParams.get('path') ?? ''
      const dirPath = rawPath ? resolvePath(rawPath) : allowedDir

      const entries = await readdir(dirPath, { withFileTypes: true })
      const items = await Promise.all(entries.map(async (entry) => {
        const fullPath = join(dirPath, entry.name)
        let size = 0
        let mtime = ''
        try {
          const st = await stat(fullPath)
          size = st.size
          mtime = st.mtime.toISOString()
        } catch {
          // Best effort metadata.
        }
        return {
          name: entry.name,
          isDirectory: entry.isDirectory(),
          size,
          mtime,
          path: relative(allowedDir, fullPath),
        }
      }))
      // Sort directories first, then files alphabetically.
      items.sort((a, b) => {
        if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1
        return a.name.localeCompare(b.name)
      })

      res.writeHead(200, { 'content-type': 'application/json;charset=utf-8' })
      res.end(JSON.stringify({ ok: true, path: dirPath, base: allowedDir, items }))
    } catch (error) {
      res.writeHead(500, { 'content-type': 'application/json;charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }))
    }
  }

  /** Serve GET /paper-reader/read?path=<path> - read a file. */
  async function serveRead(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      res.writeHead(405)
      res.end()
      return
    }
    try {
      const url = new URL(req.url ?? '/', 'http://x')
      const rawPath = url.searchParams.get('path')
      if (!rawPath) {
        res.writeHead(400, { 'content-type': 'application/json;charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: 'Missing path parameter' }))
        return
      }
      const filePath = resolvePath(rawPath)
      const st = await stat(filePath)
      if (st.isDirectory()) {
        res.writeHead(400, { 'content-type': 'application/json;charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: 'Path is a directory, not a file' }))
        return
      }

      const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
      const isBinary = [
        'pdf',
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'bmp',
        'ico',
        'zip',
        'gz',
        'tar',
        '7z',
        'rar',
        'mp3',
        'mp4',
        'mov',
        'avi',
        'exe',
        'dll',
        'so',
        'dylib',
        'bin',
        'dat',
      ].includes(ext)

      if (isBinary) {
        res.writeHead(400, { 'content-type': 'application/json;charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: `Cannot display binary file (.${ext})` }))
        return
      }

      const content = await readFile(filePath, 'utf-8')
      res.writeHead(200, { 'content-type': 'application/json;charset=utf-8' })
      res.end(JSON.stringify({
        ok: true,
        path: filePath,
        name: filePath.split('/').pop() ?? '',
        size: st.size,
        content,
      }))
    } catch (error) {
      res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }))
    }
  }

  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: '/paper-reader/files', handler: serveFiles }),
    'paper-reader: files route',
  )
  ctx.effect(
    () => ctx.webServer.register({ kind: 'prefix', path: '/paper-reader/read', handler: serveRead }),
    'paper-reader: read route',
  )

  // --- paper_load ---------------------------------------------------------
  ctx.tools.register(defineTool({
    name: 'paper_load',
    description: 'Load a paper for translation and Q&A. Pass either text directly or a local file path (plain text or PDF).',
    parameters: {
      text: { type: 'string', description: 'Paper text content. Provide either text or path.' },
      path: { type: 'string', description: 'Absolute path to a .txt or .pdf file.' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          chars: { type: 'number' },
          preview: { type: 'string' },
        },
      },
      render: (_args, value) => [{ type: 'text', text: `Loaded paper (${value.chars} chars). Preview: ${value.preview}` }],
    },
    async execute(args, exec) {
      let text = args.text ?? ''
      if (args.path){
        const buf = await readFile(args.path)
        if (args.path.endsWith('.pdf')) {
          const pdf = await import('pdf-parse')
          const data = await pdf.default(buf)
          text = data.text
        } else {
          text = buf.toString('utf8')
        }
      }
      if (!text.trim()) {
        throw new Error('paper_load: no text provided (pass text or a readable path)')
      }
      papers.set(exec.agent.id, text)
      exec.agent.session.append('paper/loaded', { chars: text.length, preview: text.slice(0, 200) })
      return { ok: true, chars: text.length, preview: text.slice(0, 200) }
    },
  }))

  // --- paper_translate ----------------------------------------------------
  ctx.tools.register(defineTool({
    name: 'paper_translate',
    description: 'Translate the loaded paper into Chinese. Call paper_load first.',
    parameters: {
      targetLanguage: { type: 'string', description: 'Target language, default Chinese.' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { ok: { type: 'boolean' }, translation: { type: 'string' } },
      },
      render: (_args, value) => [{ type: 'text', text: value.translation }],
    },
    async execute(args, exec) {
      const paper = papers.get(exec.agent.id)
      if (!paper) throw new Error('paper_translate: no paper loaded - call paper_load first')
      const target = args.targetLanguage || 'Chinese'
      const system = `You are a professional academic translator. Translate the following paper into ${target}. Preserve the original structure (headings, paragraphs, lists, code blocks). Output only the translation, no commentary.`
      const chunkSize = 6000
      const chunks: string[] = []
      for (let i = 0; i < paper.length; i += chunkSize) {
        chunks.push(paper.slice(i, i + chunkSize))
      }
      const parts: string[] = []
      for (const chunk of chunks) {
        const out = await llmText(ctx, exec, system, chunk)
        parts.push(out)
      }
      const translation = parts.join('\n\n')
      exec.agent.session.append('paper/translated', { translation })
      return { ok: true, translation }
    },
  }))

  // --- paper_qa -----------------------------------------------------------
  ctx.tools.register(defineTool({
    name: 'paper_qa',
    description: 'Answer a question based on the loaded paper. Call paper_load first.',
    parameters: {
      question: { type: 'string', required: true, description: 'The question to answer.' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { ok: { type: 'boolean' }, answer: { type: 'string' } },
      },
      render: (_args, value) => [{ type: 'text', text: value.answer }],
    },
    async execute(args, exec) {
      const paper = papers.get(exec.agent.id)
      if (!paper) throw new Error('paper_qa: no paper loaded - call paper_load first')
      const system = 'You are a research assistant. Answer the user\'s question using ONLY the provided paper content. If the answer is not in the paper, say so. Cite relevant passages.'
      const userText = `Paper content:\n\n${paper.slice(0, 24000)}\n\nQuestion: ${args.question}`
      const answer = await llmText(ctx, exec, system, userText)
      exec.agent.session.append('paper/answered', { question: args.question, answer })
      return { ok: true, answer }
    },
  }))
}
