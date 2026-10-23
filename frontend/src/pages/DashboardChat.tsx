import React, { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sidebar } from '../components/Sidebar'
import { FileManager } from '../components/FileManager'
import { ChatWindow } from '../components/ChatWindow'
import { SettingsModal } from '../components/SettingsModal'
import { chatApi, filesApi } from '../api/client'

export const DashboardChat: React.FC = () => {
  const queryClient = useQueryClient()

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set())
  const [isFileManagerOpen, setIsFileManagerOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)

  // 1. Fetch Chat Sessions
  const { data: sessions = [], refetch: refetchSessions } = useQuery({
    queryKey: ['chatSessions'],
    queryFn: chatApi.listSessions,
  })

  // 2. Fetch Document Files
  const { data: files = [], refetch: refetchFiles } = useQuery({
    queryKey: ['documentFiles'],
    queryFn: filesApi.list,
  })

  // 3. Auto-select first session if none selected, or create one if empty
  useEffect(() => {
    if (!activeSessionId && sessions.length > 0) {
      setActiveSessionId(sessions[0].id)
    }
  }, [sessions, activeSessionId])

  // 4. Fetch Messages for Active Session
  const { data: messages = [], refetch: refetchMessages } = useQuery({
    queryKey: ['sessionMessages', activeSessionId],
    queryFn: () => (activeSessionId ? chatApi.getSessionMessages(activeSessionId) : []),
    enabled: Boolean(activeSessionId),
  })

  // 5. Create Session Mutation
  const createSessionMutation = useMutation({
    mutationFn: (title?: string) => chatApi.createSession(title),
    onSuccess: (newSession) => {
      queryClient.setQueryData(['chatSessions'], (old: typeof sessions = []) => [
        newSession,
        ...old,
      ])
      setActiveSessionId(newSession.id)
    },
  })

  // 6. Delete Session Mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedSessionId) => {
      queryClient.setQueryData(['chatSessions'], (old: typeof sessions = []) =>
        old.filter((s) => s.id !== deletedSessionId)
      )
      if (activeSessionId === deletedSessionId) {
        const remaining = sessions.filter((s) => s.id !== deletedSessionId)
        setActiveSessionId(remaining.length > 0 ? remaining[0].id : null)
      }
    },
  })

  // 7. Delete File Mutation
  const deleteFileMutation = useMutation({
    mutationFn: (fileId: string) => filesApi.delete(fileId),
    onSuccess: (_, deletedFileId) => {
      queryClient.setQueryData(['documentFiles'], (old: typeof files = []) =>
        old.filter((f) => f.id !== deletedFileId)
      )
      setSelectedFileIds((prev) => {
        const next = new Set(prev)
        next.delete(deletedFileId)
        return next
      })
    },
  })

  const handleNewChat = async () => {
    await createSessionMutation.mutateAsync('New Chat')
  }

  const handleToggleSelectFile = (fileId: string) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev)
      if (next.has(fileId)) {
        next.delete(fileId)
      } else {
        next.add(fileId)
      }
      return next
    })
  }

  const handleSelectAllFiles = (selectAll: boolean) => {
    if (selectAll) {
      setSelectedFileIds(new Set(files.map((f) => f.id)))
    } else {
      setSelectedFileIds(new Set())
    }
  }

  const activeSession = sessions.find((s) => s.id === activeSessionId)
  const selectedFileNames = files
    .filter((f) => selectedFileIds.has(f.id))
    .map((f) => f.filename)

  return (
    <div className="flex h-screen w-screen bg-surface-950 overflow-hidden font-sans">
      {/* Sidebar */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => setActiveSessionId(id)}
        onNewChat={handleNewChat}
        onDeleteSession={(id) => deleteSessionMutation.mutate(id)}
        onToggleFileManager={() => setIsFileManagerOpen(true)}
        onToggleSettings={() => setIsSettingsOpen(true)}
        fileCount={files.length}
        selectedFileCount={selectedFileIds.size}
      />

      {/* Main Chat Area */}
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        {activeSessionId ? (
          <ChatWindow
            key={activeSessionId}
            sessionId={activeSessionId}
            sessionTitle={activeSession?.title}
            messages={messages}
            selectedFileIds={selectedFileIds}
            selectedFileNames={selectedFileNames}
            onMessagesUpdated={() => {
              refetchMessages()
              refetchSessions()
            }}
            onClearScopedFiles={() => setSelectedFileIds(new Set())}
            onOpenFileManager={() => setIsFileManagerOpen(true)}
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
            <h2 className="text-xl font-semibold text-white mb-2">No Chat Selected</h2>
            <p className="text-sm text-slate-400 mb-6">
              Create a new conversation to start chatting with your documents.
            </p>
            <button
              onClick={handleNewChat}
              className="bg-brand-600 hover:bg-brand-500 text-white font-medium px-5 py-2.5 rounded-xl text-sm transition-all shadow-lg shadow-brand-600/25 cursor-pointer"
            >
              Start New Chat
            </button>
          </div>
        )}
      </main>

      {/* File Manager Modal */}
      <FileManager
        files={files}
        selectedFileIds={selectedFileIds}
        onToggleSelectFile={handleToggleSelectFile}
        onSelectAllFiles={handleSelectAllFiles}
        onDeleteFile={async (id) => {
          await deleteFileMutation.mutateAsync(id)
        }}
        onFilesUpdated={() => refetchFiles()}
        isOpen={isFileManagerOpen}
        onClose={() => setIsFileManagerOpen(false)}
      />

      {/* Account Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  )
}
