/**
 *Paper Reader plugin— client (browser)side.
 *
 * Showsa floatingpanel.When opened, it displays the workspace filesina
 *file browser. Clickinga file opensa left-right split reader:
 *- Left: originaltext (selectable)
 *- Right: translationof selectedtext (or fulltranslation)
 *- Bottom: Q&A chatarea
 *
 * File listing isfetched from the host HTTPendpoints.
 * Translationand Q&A use steer promptsto callthe host-side tools.
 */
import {createElement, useEffect, useState, useCallback,useRef} from 'react'
import type {ClientContext }from '@deepseek-ai/dsh-client-runtime/client'

export const inject = ['slots', 'sessions']

/** File entry returnedby the host. */
interface FileEntry {
  name:string
  isDirectory:boolean
  size: number
  mtime: string
  path:string
}

/**File listingresponse.*/
interface FilesResponse {
  ok: boolean
  path:string
  base:string
  items: FileEntry[]
  error?:string
}

/**File readresponse. */
interface ReadResponse {
  ok:boolean
  path: string
  name:string
  size:number
  content: string
  error?:string
}

/**Paper reader projection state (mirrors host-side).*/
interface PaperReaderState {
  loaded: boolean
  chars:number
  preview:string
  translation: string
  qa: Array<{question:string;answer:string }>
}

const FETCH_BASE =''

export function apply(ctx: ClientContext):void {
  ctx.slots.inject('shell.overlay',() =>ctx.slots.register(
    { name: 'shell.overlay',id:'paper-reader', label: 'Paper Reader' },
    function PaperReaderPanel() {
      const sessions =ctx.sessions
      const [open,setOpen] =useState(false)
      const [activeView,setActiveView]= useState<'browser'| 'reader'>('browser')

      // File browser state
      const [currentDir,setCurrentDir]= useState('')
      const [files,setFiles] =useState<FileEntry[]>([])
      const [filePath,setFilePath] =useState('')
      const [fileLoading, setFileLoading] =useState(false)
      const [fileError, setFileError] =useState('')

      // Reader state
      const [originalText, setOriginalText] =useState('')
      const [fileName,setFileName] =useState('')
      const [translation,setTranslation] =useState('')
      const [selectedText, setSelectedText] =useState('')
      const [translating,setTranslating]= useState(false)
      const [translationError, setTranslationError] =useState('')

      // QA chat state
      const [qaMessages, setQaMessages] =useState<Array<{role:'user'| 'assistant'; text: string}>>([])
      const [qaInput, setQaInput]= useState('')
      const [qaLoading, setQaLoading]= useState(false)
      const [status,setStatus] =useState('')
      const [error,setError] =useState('')
      const [currentSession,setCurrentSession]= useState(getCurrentSession)
      const chatEndRef =useRef<HTMLDivElement>(null)

      function getCurrentSession(){
        const list = sessions.list.getSnapshot()
        const currentId= list.current
        return currentId ? sessions.binding(currentId)?.session : undefined
      }

      // Update current session
      useEffect(() =>{
        const updateCurrentSession= ()=> setCurrentSession(getCurrentSession())
        updateCurrentSession()
        const subscribe = (sessions.list as {subscribe?:(listener:()=> void) =>() =>void}).subscribe
        if (typeof subscribe !== 'function') return undefined
        return subscribe.call(sessions.list, updateCurrentSession)
      },[sessions])

      // WatchpaperReader projection
      useEffect(()=> {
        if (!currentSession) return
        const face =currentSession.projections.faceOf('paperReader')
        const read= (): PaperReaderState | undefined=> face.getSnapshot()as PaperReaderState | undefined
        const update =(): void=> {
          const state =read()
          if(!state) return
          if (state.translation) {
            setTranslation(state.translation)
            setTranslating(false)
            setStatus('')
            setError('')
          }
          if (state.qa.length >0) {
            const last =state.qa[state.qa.length -1]
            setQaMessages(prev=> {
              const lastUser = prev[prev.length -1]
              if (lastUser && lastUser.role ==='user' &&lastUser.text ===last.question){
                if (prev.some(m =>m.role ==='assistant'&&m.text === last.answer)) return prev
                return [...prev,{ role: 'assistant', text: last.answer }]
              }
              return prev
            })
            setQaLoading(false)
            setStatus('')
            setError('')
          }
        }
        update()
        const off= face.subscribe(update)
        return off
      },[currentSession])

      // Scroll chat to bottom
      useEffect(()=> {
        chatEndRef.current?.scrollIntoView({behavior: 'smooth' })
      }, [qaMessages])

      // Load fileswhen panelopens
      useEffect(()=> {
        if(open&&activeView=== 'browser') {
          loadFiles('')
        }
      }, [open,activeView])

      const loadFiles =useCallback(async (dir:string)=> {
        setFileLoading(true)
        setFileError('')
        try{
          const params= dir ? `?path=${encodeURIComponent(dir)}` :''
          const res =await fetch(`${FETCH_BASE}/paper-reader/files${params}`)
          const data:FilesResponse = await res.json()
          if(data.ok){
            setFiles(data.items)
            setCurrentDir(data.path)
          } else {
            setFileError(data.error ||'Failedto list files')
          }
        } catch(err) {
          setFileError(err instanceof Error ?err.message :String(err))
        } finally {
          setFileLoading(false)
        }
      },[])

      const readFile =useCallback(async (path:string) =>{
        setFileLoading(true)
        setFileError('')
        try{
          const res= await fetch(`${FETCH_BASE}/paper-reader/read?path=${encodeURIComponent(path)}`)
          const data: ReadResponse =await res.json()
          if(data.ok) {
            setOriginalText(data.content)
            setFileName(data.name)
            setFilePath(path)
            setTranslation('')
            setSelectedText('')
            setActiveView('reader')
            // Auto-load thepaper for Q&A via steer
            await loadPaperViaSteer(data.content)
          }else {
            setFileError(data.error ||'Failedto readfile')
          }
        }catch (err){
          setFileError(err instanceof Error ?err.message :String(err))
        } finally{
          setFileLoading(false)
        }
      },[])

      async function loadPaperViaSteer(text:string){
        const session =getCurrentSession()
        if(!session) {
          setError('Noactive session. Please open or createa conversation first.')
          return
        }
        setStatus('Loadingpaper into session...')
        try {
          const result =await session.prompt(
            [{ type: 'text', text: `Call thepaper_load toolwith thistext:\n\n${text.slice(0,50000)}`}],
            'steer'
          )
          if (!result.ok) {
            setError(result.error.message)
          } else {
            setStatus('Paper loaded. Readyfor translation andQ&A.')
          }
        } catch(err) {
          setError(err instanceof Error ?err.message : String(err))
        }
      }

      async function steer(prompt: string): Promise<boolean>{
        const session= getCurrentSession()
        setCurrentSession(session)
        if(!session) {
          setError('Noactive session. Please open or createa conversation first.')
          setStatus('')
          setTranslating(false)
          setQaLoading(false)
          return false
        }
        try {
          const result =await session.prompt([{ type: 'text',text:prompt }], 'steer')
          if(!result.ok) {
            setError(result.error.message)
            setStatus('')
            setTranslating(false)
            setQaLoading(false)
            return false
          }
          return true
        } catch(err) {
          setError(err instanceof Error ?err.message :String(err))
          setStatus('')
          setTranslating(false)
          setQaLoading(false)
          return false
        }
      }

      async function handleTranslatePaper(){
        if(!originalText.trim()) {
          setError('Nopaper loaded. Please opena file first.')
          return
        }
        setTranslating(true)
        setTranslation('')
        setStatus('Sending translationrequest...')
        setError('')
        await steer(
          `Callpaper_translate to translate the loadedpaper intoChinese.`
        )
      }

      async function handleTranslateSelection() {
        if(!selectedText.trim()) {
          setTranslationError('Please select some text first.')
          return
        }
        setTranslating(true)
        setTranslation('')
        setTranslationError('')
        setStatus('Translating selectedtext...')
        // For selectedtext translation, we don't use the paper_translate tool
        // (which translatesthe entire paper).Instead, we senda direct prompt.
        const session=getCurrentSession()
        if(!session){
          setError('No active session.')
          setTranslating(false)
          return
        }
        try{
          const result = await session.prompt(
            [{type:'text', text: `Translate the following text to Chinese. Output ONLY the translation,no explanationor commentary:\n\n${selectedText}`}],
            'steer'
          )
          if(result.ok){
            // TheLLM willrespond withthe translationdirectlyin the conversation
            setStatus('Translation request sent.Check the conversation for the result.')
          } else {
            setError(result.error.message)
          }
        }catch (err){
          setError(err instanceof Error ?err.message : String(err))
        }finally{
          setTranslating(false)
        }
      }

      async function handleAsk(){
        if(!qaInput.trim())return
        const question =qaInput.trim()
        setQaMessages(prev =>[...prev,{ role: 'user',text:question }])
        setQaInput('')
        setQaLoading(true)
        setStatus('Sending Q&A request...')
        setError('')
        const hasPaper =originalText.trim().length>0
        await steer(
          hasPaper
            ?`Callpaper_qa withthisquestion:${question}`
            : `Answer thisquestion: ${question}`
        )
      }

      // Handle text selectionin the original text
      function handleTextSelect(){
        const selection =window.getSelection()
        const text =selection?.toString().trim()||""
        setSelectedText(text)
        if (text){
          setTranslationError('')
        }
      }

      // ---Render helpers---

      function renderFileBrowser() {
        return createElement('div', {
          style: {
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            background:'var(--dsw-bg-secondary, #16213e)',
          },
        },
          createElement('div', {
            style:{
              padding: '12px16px',
              fontWeight:600,
              borderBottom:'1px solidvar(--dsw-border, #333)',
              color: 'var(--dsw-text,#e0e0e0)',
              fontSize:14,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            },
          },
            createElement('span', null, '\uD83D\uDCC1 Workspace Files'),
            createElement('button', {
              onClick: ()=> loadFiles(currentDir),
              style:{
                background: 'transparent',
                border: '1pxsolid var(--dsw-border, #444)',
                color: 'var(--dsw-text, #e0e0e0)',
                borderRadius:4,
                padding:'4px8px',
                fontSize:12,
                cursor: 'pointer',
              },
            },'\u21BB Refresh'),
          ),
          fileError &&createElement('div',{
            style: {padding:'8px12px', color: '#fca5a5',fontSize:12,background:'rgba(127,29,29,0.25)' },
          },fileError),
          fileLoading
            ?createElement('div', {
              style: {padding:20,textAlign: 'center',color:'var(--dsw-text-secondary,#888)' },
            },'Loading...')
            :createElement('div',{
              style:{ flex:1,overflow:'auto', padding: '4px0' },
            },
              // Parent directory navigation
              currentDir && currentDir !== '.'&& createElement('div', {
                onClick: ()=> {
                  const parts =currentDir.split('/')
                  parts.pop()
                  loadFiles(parts.join('/')|| '')
                },
                style: {
                  padding: '8px16px',
                  cursor: 'pointer',
                  color: 'var(--dsw-accent, #4f46e5)',
                  fontSize:13,
                  display: 'flex',
                  alignItems: 'center',
                  gap:6,
                  borderBottom:'1pxsolid var(--dsw-border, #222)',
                },
              },'\uD83D\uDCC2 ..'),
              // File entries
              ...files.map((entry, i) =>
                createElement('div', {
                  key: i,
                  onClick: ()=> {
                    if(entry.isDirectory) {
                      loadFiles(entry.path)
                    }else {
                      readFile(entry.path)
                    }
                  },
                  style: {
                    padding: '8px16px',
                    cursor:'pointer',
                    display:'flex',
                    alignItems:'center',
                    gap:8,
                    fontSize:13,
                    color: 'var(--dsw-text, #e0e0e0)',
                    borderBottom:'1px solidvar(--dsw-border,#222)',
                    transition: 'background0.15s',
                  },
                  onMouseEnter: (e:any)=> {e.currentTarget.style.background ='var(--dsw-hover, rgba(255,255,255,0.05))'},
                  onMouseLeave: (e:any)=> {e.currentTarget.style.background ='transparent'},
                },
                  createElement('span',{ style: {fontSize:16} },entry.isDirectory? '\uD83D\uDCC1': '\uD83D\uDCC4'),
                  createElement('span',{style:{ flex:1,overflow:'hidden', textOverflow: 'ellipsis', whiteSpace:'nowrap' as const }}, entry.name),
                  !entry.isDirectory &&createElement('span',{
                    style:{ fontSize:11,color:'var(--dsw-text-secondary,#666)' },
                  },formatSize(entry.size)),
                ),
              ),
              files.length===0&& !fileLoading&& createElement('div',{
                style:{ padding:20, textAlign:'center',color:'var(--dsw-text-secondary,#888)', fontSize:13 },
              }, 'No filesfound'),
            ),
        )
      }

      function renderReader() {
        return createElement('div', {
          style:{
            display: 'flex',
            flexDirection:'row',
            height: '100%',
            flex:1,
          },
        },
          // Left: Originaltext
          createElement('div',{
            style:{
              flex:1,
              display: 'flex',
              flexDirection:'column',
              borderRight: '1pxsolid var(--dsw-border, #333)',
              minWidth:0,
            },
          },
            createElement('div', {
              style: {
                padding: '10px16px',
                fontWeight:600,
                borderBottom:'1px solidvar(--dsw-border, #333)',
                color:'var(--dsw-text, #e0e0e0)',
                fontSize:13,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background:'var(--dsw-bg-secondary, #16213e)',
              },
            },
              createElement('span',null,`\uD83D\uDCC4 ${fileName}`),
              createElement('div',{ style: {display:'flex', gap:6 }},
                createElement('button',{
                  onClick:() =>setActiveView('browser'),
                  style: {
                    background: 'transparent',
                    border: '1pxsolid var(--dsw-border, #444)',
                    color: 'var(--dsw-text, #e0e0e0)',
                    borderRadius:4,
                    padding: '3px8px',
                    fontSize:11,
                    cursor: 'pointer',
                  },
                },'\u2190Back'),
                createElement('button', {
                  onClick: handleTranslatePaper,
                  disabled: translating,
                  style:{
                    background: translating? '#555': 'var(--dsw-accent,#4f46e5)',
                    border:'none',
                    color:'white',
                    borderRadius:4,
                    padding: '3px10px',
                    fontSize:11,
                    cursor: translating? 'not-allowed' :'pointer',
                  },
                },translating ?'...' :'\uD83C\uDF10Translate All'),
              ),
            ),
            createElement('div',{
              onMouseUp: handleTextSelect,
              style: {
                flex:1,
                padding:16,
                overflow: 'auto',
                color: 'var(--dsw-text,#e0e0e0)',
                fontSize:14,
                lineHeight:1.7,
                whiteSpace:'pre-wrap' as const,
                fontFamily: 'Georgia,serif',
                userSelect: 'text' as const,
              },
            },originalText ||(fileLoading ?'Loading...': '')),
            selectedText && createElement('div',{
              style: {
                padding: '8px12px',
                borderTop: '1pxsolid var(--dsw-border, #333)',
                background: 'var(--dsw-bg-secondary, #16213e)',
                display:'flex',
                alignItems:'center',
                gap:8,
                fontSize:12,
              },
            },
                createElement('span', {style:{ color: 'var(--dsw-text-secondary,#888)',flex:1,overflow:'hidden', textOverflow: 'ellipsis',whiteSpace:'nowrap' as const } },
                `Selected:"${selectedText.slice(0,60)}${selectedText.length >60? '...': ''}"`),
              createElement('button',{
                onClick:handleTranslateSelection,
                disabled: translating,
                style:{
                  background: translating? '#555' :'var(--dsw-accent,#4f46e5)',
                  border:'none',
                  color:'white',
                  borderRadius:4,
                  padding: '4px10px',
                  fontSize:11,
                  cursor: translating? 'not-allowed': 'pointer',
                  whiteSpace:'nowrap' as const,
                },
              }, translating?'Translating...' :'\uD83C\uDF10Translate Selection'),
            ),
          ),

          // Right: Translation+ QA
          createElement('div', {
            style: {
              flex:1,
              display: 'flex',
              flexDirection:'column',
              minWidth:0,
            },
          },
            // Translationarea
            createElement('div',{
              style: {
                flex:1,
                display: 'flex',
                flexDirection:'column',
                minHeight:0,
              },
            },
              createElement('div', {
                style: {
                  padding: '10px16px',
                  fontWeight:600,
                  borderBottom:'1pxsolid var(--dsw-border,#333)',
                  color: 'var(--dsw-text, #e0e0e0)',
                  fontSize:13,
                  background: 'var(--dsw-bg-secondary,#16213e)',
                },
              },'\uD83C\uDF10 Translation'),
              translationError && createElement('div',{
                style:{ padding: '6px12px',color:'#fca5a5', fontSize:12,background:'rgba(127,29,29,0.25)' },
              },translationError),
              createElement('div',{
                style:{
                  flex:1,
                  padding:16,
                  overflow: 'auto',
                  color: 'var(--dsw-text, #e0e0e0)',
                  fontSize:14,
                  lineHeight:1.7,
                  whiteSpace: 'pre-wrap' as const,
                  fontFamily: 'Georgia,serif',
                },
              },
                translation
                  ? translation
                  :createElement('span', {style:{ color: 'var(--dsw-text-secondary,#666)' }},
                    selectedText
                      ?'Click"Translate Selection"to translate the selectedtext.'
                      :'Click"Translate All"to translate the entire paper,or select text totranslatea specific passage.'
                  ),
              ),
            ),

            // Divider
            createElement('div',{
              style: {height:1,background:'var(--dsw-border, #333)'},
            }),

            // QA Chatarea
            createElement('div',{
              style:{
                height:220,
                display:'flex',
                flexDirection: 'column',
                borderTop: '1pxsolid var(--dsw-border, #333)',
              },
            },
              createElement('div',{
                style: {
                  padding: '8px12px',
                  fontWeight:600,
                  borderBottom:'1pxsolid var(--dsw-border, #333)',
                  color:'var(--dsw-text, #e0e0e0)',
                  fontSize:12,
                  background: 'var(--dsw-bg-secondary, #16213e)',
                  display: 'flex',
                  alignItems:'center',
                  justifyContent:'space-between',
                },
              },
                createElement('span', null, '\uD83D\uDCAC Q&A'),
                createElement('span', {style:{ fontSize:11,color:'var(--dsw-text-secondary, #666)'} },'Askquestions about thepaper'),
              ),
              status &&createElement('div',{
                style: {padding:'5px12px',color:'var(--dsw-text, #e0e0e0)', fontSize:11,background:'var(--dsw-input, #2a2a2a)' },
              },status),
              error &&createElement('div', {
                style: {padding:'5px12px', color: '#fca5a5', fontSize:11, background: 'rgba(127,29,29,0.25)' },
              },error),
              createElement('div', {
                style: {flex:1, overflow: 'auto',padding:8,display:'flex', flexDirection:'column', gap:6 },
              },
                ...qaMessages.map((msg,i)=>
                  createElement('div', {
                    key: i,
                    style:{
                      padding: '6px10px',
                      borderRadius:8,
                      maxWidth:'85%',
                      alignSelf: msg.role ==='user' ? 'flex-end' as const : 'flex-start' as const,
                      background: msg.role === 'user'? 'var(--dsw-accent,#4f46e5)' :'var(--dsw-input, #2a2a2a)',
                      color: 'var(--dsw-text, #e0e0e0)',
                      fontSize:13,
                      lineHeight:1.4,
                    wordBreak: 'break-word' as const,
                    },
                  }, msg.text),
                ),
                qaLoading&& createElement('div', {
                  style: {
                    padding: '6px10px',
                    borderRadius:8,
                    maxWidth:'60%',
                    alignSelf:'flex-start' as const,
                    background: 'var(--dsw-input,#2a2a2a)',
                    color:'var(--dsw-text-secondary,#888)',
                    fontSize:13,
                    fontStyle:'italic' as const,
                  },
                },'Thinking...'),
                createElement('div',{ ref: chatEndRef}),
              ),
              createElement('div', {
                style: {display:'flex', gap:6,padding: '6px10px',borderTop: '1px solidvar(--dsw-border, #444)'},
              },
                createElement('input', {
                  value: qaInput,
                  onChange:(e:any)=> setQaInput(e.target.value),
                  onKeyDown: (e:any) =>{ if(e.key ==='Enter') handleAsk()},
                  placeholder: 'Aska question about the paper...',
                  disabled:qaLoading,
                  style: {
                    flex:1,
                    padding:'6px10px',
                    borderRadius:6,
                    border: '1pxsolid var(--dsw-border, #444)',
                    background: 'var(--dsw-input, #2a2a2a)',
                    color:'var(--dsw-text,#fff)',
                    fontSize:13,
                    outline: 'none',
                  },
                }),
                createElement('button', {
                  onClick: handleAsk,
                  disabled: qaLoading|| !qaInput.trim(),
                  style: {
                    padding: '6px14px',
                    borderRadius:6,
                    border: 'none',
                    background: qaLoading?'#555' :'var(--dsw-accent, #4f46e5)',
                    color:'white',
                    cursor:qaLoading? 'not-allowed': 'pointer',
                    fontSize:13,
                    fontWeight:500,
                  },
                },'Ask'),
              ),
            ),
          ),
        )
      }

      return createElement('div', {style: {position:'fixed', bottom:20,right:20, zIndex:9999} },
        open
          ?createElement('div', {
            style: {
              position: 'fixed',
              inset:0,
              background: 'rgba(0,0,0,0.7)',
              display:'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex:10000,
            },
            onClick: ()=> setOpen(false),
          },
            createElement('div', {
              style: {
                width: '95vw',
                height: '92vh',
                background:'var(--dsw-bg,#1a1a2e)',
                borderRadius:12,
                display:'flex',
                flexDirection: 'row',
                overflow: 'hidden',
                border: '1pxsolid var(--dsw-border, #333)',
                boxShadow: '08px32px rgba(0,0,0,0.4)',
              },
              onClick:(e: MouseEvent)=>e.stopPropagation(),
            },
              // Left sidebar:File browser (260px)
              (activeView=== 'browser' ||activeView=== 'reader')
                ?createElement('div',{
                  style: {
                    width:260,
                    minWidth:260,
                    borderRight: '1pxsolid var(--dsw-border, #333)',
                    display:'flex',
                    flexDirection: 'column',
                  },
                },renderFileBrowser())
                : null,
              // Maincontentarea
              createElement('div',{
                style:{
                  flex:1,
                  display: 'flex',
                  flexDirection:'column',
                  minWidth:0,
                },
              },
                activeView=== 'browser'
                  ?createElement('div', {
                    style: {
                      flex:1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color:'var(--dsw-text-secondary,#666)',
                      fontSize:15,
                    },
                  },
                    createElement('div', {style:{ textAlign: 'center'} },
                      createElement('div', {style:{ fontSize:48,marginBottom:16} },'\uD83D\uDCC4'),
                      createElement('div',null,'Select a file from the sidebar tostart reading'),
                      createElement('div',{ style: {fontSize:13, marginTop:8, color: 'var(--dsw-text-secondary,#888)'} },
                        'Supported:.txt, .md,.py, .js,.ts,.html, .css,.json, .yaml, .xml, .csv'
                      ),
                    ),
                  )
                  : renderReader(),
              ),
            ),
          )
          : createElement('button',{
            onClick: ()=> {
              setActiveView('browser')
              setOpen(true)
            },
            style: {
              width:52,
              height:52,
              borderRadius: '50%',
              border:'none',
              background: 'var(--dsw-accent,#4f46e5)',
              color:'white',
              fontSize:22,
              cursor:'pointer',
              boxShadow: '04px12pxrgba(0,0,0,0.3)',
              display:'flex',
              alignItems:'center',
              justifyContent:'center',
              transition:'transform 0.2s',
            },
            onMouseEnter: (e:any)=> {e.currentTarget.style.transform = 'scale(1.1)' },
            onMouseLeave: (e:any)=> {e.currentTarget.style.transform ='scale(1)' },
          },'\uD83D\uDCC4'),
      )
    },
  ))
}

function formatSize(bytes: number): string{
  if (bytes ===0) return '0B'
  const k =1024
  const sizes =['B', 'KB','MB', 'GB']
  const i = Math.floor(Math.log(bytes)/ Math.log(k))
  return parseFloat((bytes/ Math.pow(k,i)).toFixed(1)) +'' +sizes[i]
}
