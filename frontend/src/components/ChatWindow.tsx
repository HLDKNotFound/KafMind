import React, { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import {
  Send,
  Square,
  Bot,
  User as UserIcon,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  BookOpen,
  Sparkles,
  Search,
  FileCheck,
  RotateCcw,
  Zap,
} from 'lucide-react'
import { ChatMessage, SourceCitation, AgentStepEvent } from '../types'
import { useAuthStore } from '../store/authStore'

interface ChatWindowProps {
  sessionId: string | null
  sessionTitle?: string
  messages: ChatMessage[]
  selectedFileIds: Set<string>
  selectedFileNames: string[]
  onMessagesUpdated: () => void
  onClearScopedFiles: () => void
  onOpenFileManager: () => void
}

const STEP_LABELS: Record<string, { label: string; icon: React.FC<{ className?: string }> }> = {
  router_node: { label: 'Analyzing user query & routing...', icon: Zap },
  retrieve_node: { label: 'Searching document vectors in Qdrant...', icon: Search },
  grade_documents_node: { label: 'Evaluating document chunk relevance...', icon: FileCheck },
  rewrite_query_node: { label: 'Optimizing search query for better recall...', icon: RotateCcw },
  generate_node: { label: 'Synthesizing response with DeepSeek...', icon: Sparkles },
}

export const ChatWindow: React.FC<ChatWindowProps> = ({
  sessionId,
  sessionTitle,
  messages,
  selectedFileIds,
  selectedFileNames,
  onMessagesUpdated,
  onClearScopedFiles,
  onOpenFileManager,
}) => {
  const token = useAuthStore((state) => state.accessToken)

  const [inputMessage, setInputMessage] = useState('')
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>(messages)
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentStep, setCurrentStep] = useState<AgentStepEvent | null>(null)
  const [copiedCodeId, setCopiedCodeId] = useState<string | null>(null)
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})

  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Sync props messages when not streaming
  useEffect(() => {
    if (!isStreaming) {
      setLocalMessages(messages)
    }
  }, [messages, isStreaming])

  // Scroll to bottom on new message / token
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages, currentStep])

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedCodeId(id)
    setTimeout(() => setCopiedCodeId(null), 2000)
  }

  const toggleSources = (msgId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }))
  }

  const handleStopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setIsStreaming(false)
    setCurrentStep(null)
  }

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!inputMessage.trim() || !sessionId || isStreaming) return

    const messageText = inputMessage.trim()
    setInputMessage('')

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    const tempUserMsgId = 'user-' + Date.now()
    const tempAssistantMsgId = 'assistant-' + Date.now()

    const userMessage: ChatMessage = {
      id: tempUserMsgId,
      session_id: sessionId,
      role: 'user',
      content: messageText,
      sources: [],
      created_at: new Date().toISOString(),
    }

    const pendingAssistantMessage: ChatMessage = {
      id: tempAssistantMsgId,
      session_id: sessionId,
      role: 'assistant',
      content: '',
      sources: [],
      created_at: new Date().toISOString(),
    }

    setLocalMessages((prev) => [...prev, userMessage, pendingAssistantMessage])
    setIsStreaming(true)
    setCurrentStep(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    let accumulatedContent = ''
    let accumulatedSources: SourceCitation[] = []

    try {
      await fetchEventSource(`/api/v1/chat/sessions/${sessionId}/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: messageText,
          selected_file_ids: selectedFileIds.size > 0 ? Array.from(selectedFileIds) : null,
        }),
        signal: controller.signal,

        onmessage(ev) {
          if (ev.event === 'agent_step') {
            try {
              const data: AgentStepEvent = JSON.parse(ev.data)
              setCurrentStep(data)
            } catch {
              // ignore json parse error
            }
          } else if (ev.event === 'token') {
            try {
              const data = JSON.parse(ev.data)
              accumulatedContent += data.token || ''

              setLocalMessages((prev) =>
                prev.map((msg) =>
                  msg.id === tempAssistantMsgId
                    ? { ...msg, content: accumulatedContent }
                    : msg
                )
              )
            } catch {
              // ignore
            }
          } else if (ev.event === 'sources') {
            try {
              const data = JSON.parse(ev.data)
              accumulatedSources = data.sources || []

              setLocalMessages((prev) =>
                prev.map((msg) =>
                  msg.id === tempAssistantMsgId
                    ? { ...msg, sources: accumulatedSources }
                    : msg
                )
              )
            } catch {
              // ignore
            }
          } else if (ev.event === 'done') {
            try {
              const data = JSON.parse(ev.data)
              setLocalMessages((prev) =>
                prev.map((msg) =>
                  msg.id === tempAssistantMsgId
                    ? {
                        ...msg,
                        id: data.message_id || msg.id,
                        content: data.content || accumulatedContent,
                        sources: data.sources || accumulatedSources,
                      }
                    : msg
                )
              )
            } catch {
              // ignore
            }
            setCurrentStep(null)
            setIsStreaming(false)
            onMessagesUpdated()
          } else if (ev.event === 'error') {
            setIsStreaming(false)
            setCurrentStep(null)
          }
        },

        onerror(err) {
          console.error('SSE Stream Error:', err)
          setIsStreaming(false)
          setCurrentStep(null)
          throw err // will stop retry
        },

        onclose() {
          setIsStreaming(false)
          setCurrentStep(null)
        },
      })
    } catch {
      setIsStreaming(false)
      setCurrentStep(null)
    } finally {
      abortControllerRef.current = null
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-surface-950 relative overflow-hidden">
      {/* Top Header */}
      <div className="h-14 border-b border-slate-800 px-6 flex items-center justify-between shrink-0 bg-surface-950/80 backdrop-blur-md z-10">
        <div className="flex items-center gap-3 truncate">
          <h1 className="text-sm font-semibold text-white truncate">
            {sessionTitle || 'New Conversation'}
          </h1>
          {selectedFileIds.size > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-brand-500/10 border border-brand-500/20 text-brand-300 text-xs">
              <span>Scoped to {selectedFileIds.size} doc(s)</span>
              <button
                type="button"
                onClick={onClearScopedFiles}
                className="text-brand-400 hover:text-white cursor-pointer ml-1"
                title="Clear file scope"
              >
                ×
              </button>
            </div>
          )}
        </div>

        <button
          onClick={onOpenFileManager}
          className="text-xs text-slate-300 hover:text-white bg-surface-850 hover:bg-surface-800 border border-slate-750 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors cursor-pointer"
        >
          <BookOpen className="w-3.5 h-3.5 text-brand-400" />
          <span>Scope Files</span>
        </button>
      </div>

      {/* Messages Scroll Container */}
      <div className="flex-1 overflow-y-auto px-4 md:px-12 py-6 space-y-6">
        {localMessages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 max-w-lg mx-auto">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shadow-xl shadow-brand-500/20 border border-brand-400/20 mb-4">
              <Sparkles className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">How can KafMind help you?</h2>
            <p className="text-sm text-slate-400 mb-6">
              Ask questions across your ingested documents. Powered by LangGraph adaptive RAG,
              FastEmbed vector embeddings, and Kafka streaming.
            </p>
            {selectedFileNames.length > 0 && (
              <div className="p-3 rounded-xl bg-surface-900 border border-slate-800 text-xs text-slate-300 flex items-center gap-2">
                <FileCheck className="w-4 h-4 text-brand-400" />
                <span>Currently scoped to: {selectedFileNames.join(', ')}</span>
              </div>
            )}
          </div>
        ) : (
          localMessages.map((msg) => {
            const isUser = msg.role === 'user'
            const hasSources = msg.sources && msg.sources.length > 0
            const isSourcesExpanded = expandedSources[msg.id] ?? false

            return (
              <div
                key={msg.id}
                className={`flex gap-3.5 ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                {!isUser && (
                  <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shrink-0 shadow-md shadow-brand-500/20 border border-brand-400/20 text-white mt-1">
                    <Bot className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={`max-w-[85%] md:max-w-[75%] rounded-2xl p-4 shadow-sm ${
                    isUser
                      ? 'bg-brand-600 text-white rounded-tr-sm'
                      : 'bg-surface-900 border border-slate-800 text-slate-100 rounded-tl-sm'
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
                  ) : (
                    <div>
                      {/* Markdown rendered content */}
                      <div className="prose prose-invert prose-sm max-w-none space-y-2 leading-relaxed">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code({ className, children, ...props }) {
                              const match = /language-(\w+)/.exec(className || '')
                              const isInline = !match && !String(children).includes('\n')
                              const codeString = String(children).replace(/\n$/, '')
                              const codeId = `${msg.id}-${codeString.slice(0, 10)}`

                              if (isInline) {
                                return (
                                  <code
                                    className="bg-surface-800 text-brand-300 px-1.5 py-0.5 rounded text-xs font-mono"
                                    {...props}
                                  >
                                    {children}
                                  </code>
                                )
                              }

                              return (
                                <div className="relative my-3 rounded-xl overflow-hidden border border-slate-800 bg-surface-950">
                                  <div className="flex items-center justify-between px-4 py-1.5 bg-surface-900 border-b border-slate-800 text-[11px] text-slate-400">
                                    <span className="font-mono">{match ? match[1] : 'code'}</span>
                                    <button
                                      type="button"
                                      onClick={() => copyToClipboard(codeString, codeId)}
                                      className="flex items-center gap-1 hover:text-white transition-colors cursor-pointer"
                                    >
                                      {copiedCodeId === codeId ? (
                                        <>
                                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                                          <span className="text-emerald-400">Copied</span>
                                        </>
                                      ) : (
                                        <>
                                          <Copy className="w-3.5 h-3.5" />
                                          <span>Copy</span>
                                        </>
                                      )}
                                    </button>
                                  </div>
                                  <pre className="p-4 text-xs font-mono overflow-x-auto text-slate-200">
                                    <code>{children}</code>
                                  </pre>
                                </div>
                              )
                            },
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      </div>

                      {/* Expandable Source Citations */}
                      {hasSources && (
                        <div className="mt-4 pt-3 border-t border-slate-800/80">
                          <button
                            type="button"
                            onClick={() => toggleSources(msg.id)}
                            className="flex items-center gap-1.5 text-xs font-medium text-brand-400 hover:text-brand-300 transition-colors cursor-pointer"
                          >
                            <BookOpen className="w-3.5 h-3.5" />
                            <span>
                              {msg.sources.length}{' '}
                              {msg.sources.length === 1 ? 'Source Citation' : 'Source Citations'}
                            </span>
                            {isSourcesExpanded ? (
                              <ChevronDown className="w-3.5 h-3.5" />
                            ) : (
                              <ChevronRight className="w-3.5 h-3.5" />
                            )}
                          </button>

                          {isSourcesExpanded && (
                            <div className="mt-2.5 space-y-2">
                              {msg.sources.map((src, idx) => (
                                <div
                                  key={idx}
                                  className="p-3 rounded-xl bg-surface-950/70 border border-slate-800 text-xs text-slate-300"
                                >
                                  <div className="flex items-center justify-between mb-1 text-[11px]">
                                    <span className="font-semibold text-brand-300 truncate max-w-[200px]">
                                      {src.filename} [chunk #{src.chunk_index}]
                                    </span>
                                    <span className="text-slate-400 font-mono">
                                      Match: {(src.score * 100).toFixed(0)}%
                                    </span>
                                  </div>
                                  <p className="text-slate-400 italic line-clamp-3 bg-surface-900/50 p-2 rounded-lg border border-slate-800/50 mt-1">
                                    "{src.text}"
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {isUser && (
                  <div className="w-8 h-8 rounded-xl bg-surface-800 border border-slate-700 flex items-center justify-center shrink-0 text-slate-300 mt-1">
                    <UserIcon className="w-4 h-4" />
                  </div>
                )}
              </div>
            )
          })
        )}

        {/* Live Agent Step Status Indicator during streaming */}
        {isStreaming && currentStep && (
          <div className="flex items-center gap-3 max-w-[75%] p-3 rounded-xl bg-surface-900/90 border border-brand-500/30 text-xs text-slate-200 animate-in fade-in">
            {(() => {
              const stepInfo = STEP_LABELS[currentStep.step] || {
                label: `Executing ${currentStep.step}...`,
                icon: Sparkles,
              }
              const IconComp = stepInfo.icon
              return (
                <>
                  <div className="w-6 h-6 rounded-lg bg-brand-500/10 flex items-center justify-center text-brand-400 animate-pulse">
                    <IconComp className="w-3.5 h-3.5" />
                  </div>
                  <div className="flex-1 truncate">
                    <div className="font-medium text-slate-100 flex items-center gap-1.5">
                      <span>{stepInfo.label}</span>
                      <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-ping" />
                    </div>
                    {currentStep.decision && (
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        Router Decision: <span className="text-brand-300">{currentStep.decision}</span>
                      </p>
                    )}
                    {currentStep.docs_count !== undefined && (
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        Retrieved <span className="text-brand-300">{currentStep.docs_count}</span> relevant chunks
                      </p>
                    )}
                  </div>
                </>
              )
            })()}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-4 md:px-12 border-t border-slate-800 bg-surface-950/80 backdrop-blur-md">
        <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto relative">
          <div className="relative flex items-end bg-surface-900 border border-slate-750 focus-within:border-brand-500 rounded-2xl shadow-xl transition-all p-2">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputMessage}
              onChange={(e) => {
                setInputMessage(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                selectedFileIds.size > 0
                  ? `Ask about selected ${selectedFileIds.size} document(s)...`
                  : 'Ask anything about your uploaded documents...'
              }
              className="w-full bg-transparent text-slate-100 placeholder:text-slate-500 text-sm px-3 py-2 resize-none focus:outline-none max-h-40 min-h-[40px]"
            />

            <div className="flex items-center gap-2 pb-1 pr-1 shrink-0">
              {isStreaming ? (
                <button
                  type="button"
                  onClick={handleStopStreaming}
                  className="bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 p-2 rounded-xl transition-colors cursor-pointer"
                  title="Stop Generating"
                >
                  <Square className="w-4 h-4 fill-current" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!inputMessage.trim() || !sessionId}
                  className="bg-brand-600 hover:bg-brand-500 disabled:opacity-30 disabled:cursor-not-allowed text-white p-2 rounded-xl transition-all shadow-md shadow-brand-600/30 cursor-pointer"
                  title="Send Message"
                >
                  <Send className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1.5 px-2">
            <span>Press Enter to send, Shift+Enter for new line</span>
            <span>DeepSeek-V4.1 Flash • FastEmbed RAG</span>
          </div>
        </form>
      </div>
    </div>
  )
}
