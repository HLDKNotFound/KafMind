import React from 'react'
import {
  MessageSquare,
  Plus,
  Trash2,
  Files,
  Settings,
  LogOut,
  Bot,
  User as UserIcon,
} from 'lucide-react'
import { ChatSession } from '../types'
import { useAuthStore } from '../store/authStore'

interface SidebarProps {
  sessions: ChatSession[]
  activeSessionId: string | null
  onSelectSession: (sessionId: string) => void
  onNewChat: () => void
  onDeleteSession: (sessionId: string) => void
  onToggleFileManager: () => void
  onToggleSettings: () => void
  fileCount: number
  selectedFileCount: number
}

export const Sidebar: React.FC<SidebarProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onToggleFileManager,
  onToggleSettings,
  fileCount,
  selectedFileCount,
}) => {
  const { user, logout } = useAuthStore()

  return (
    <aside className="w-72 bg-surface-900 border-r border-slate-800 flex flex-col h-full shrink-0 select-none">
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shadow-md shadow-brand-600/20 border border-brand-400/20">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h2 className="font-bold text-white text-base leading-none">
              Kaf<span className="text-brand-400">Mind</span>
            </h2>
            <span className="text-[10px] text-slate-400 font-medium tracking-wider uppercase">
              Agentic RAG
            </span>
          </div>
        </div>
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 bg-brand-600/10 hover:bg-brand-600/20 text-brand-400 border border-brand-500/20 hover:border-brand-500/40 py-2.5 px-4 rounded-xl font-medium text-sm transition-all duration-150 cursor-pointer group"
        >
          <Plus className="w-4 h-4 transition-transform group-hover:rotate-90 duration-200" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Chat Sessions History List */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-1">
        <div className="px-2 py-1.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
          Recent Conversations
        </div>

        {sessions.length === 0 ? (
          <div className="text-center py-8 px-4 text-xs text-slate-500">
            No conversations yet.<br />Start a new chat above!
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === activeSessionId
            return (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`group flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-all cursor-pointer ${
                  isActive
                    ? 'bg-brand-600/20 text-white font-medium border border-brand-500/30'
                    : 'text-slate-300 hover:bg-surface-800/80 hover:text-white'
                }`}
              >
                <div className="flex items-center gap-2.5 truncate flex-1 min-w-0 pr-2">
                  <MessageSquare
                    className={`w-4 h-4 shrink-0 ${
                      isActive ? 'text-brand-400' : 'text-slate-400 group-hover:text-slate-300'
                    }`}
                  />
                  <span className="truncate">{session.title || 'Untitled Session'}</span>
                </div>

                <button
                  type="button"
                  aria-label="Delete chat session"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteSession(session.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 hover:text-red-400 text-slate-500 p-1 rounded-md transition-all cursor-pointer shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )
          })
        )}
      </div>

      {/* Bottom Actions: File Manager & Account Settings */}
      <div className="p-3 border-t border-slate-800 space-y-1 bg-surface-900/50">
        {/* File Manager Trigger */}
        <button
          onClick={onToggleFileManager}
          className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm text-slate-300 hover:bg-surface-800/80 hover:text-white transition-all cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <Files className="w-4 h-4 text-brand-400" />
            <span>Document Files</span>
          </div>
          <span className="text-xs bg-surface-800 text-slate-300 px-2 py-0.5 rounded-full border border-slate-700 font-mono">
            {selectedFileCount > 0 ? `${selectedFileCount}/${fileCount}` : fileCount}
          </span>
        </button>

        {/* Account Settings Trigger */}
        <button
          onClick={onToggleSettings}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm text-slate-300 hover:bg-surface-800/80 hover:text-white transition-all cursor-pointer"
        >
          <Settings className="w-4 h-4 text-slate-400" />
          <span>Account & Prompt</span>
        </button>

        {/* User Profile & Logout */}
        <div className="pt-2 mt-1 border-t border-slate-800/70 flex items-center justify-between px-2">
          <div className="flex items-center gap-2 min-w-0 pr-2">
            <div className="w-7 h-7 rounded-lg bg-surface-800 border border-slate-700 flex items-center justify-center text-xs font-semibold text-brand-400 shrink-0">
              {user?.full_name ? user.full_name.charAt(0).toUpperCase() : <UserIcon className="w-3.5 h-3.5" />}
            </div>
            <div className="truncate">
              <p className="text-xs font-medium text-white truncate">
                {user?.full_name || user?.email}
              </p>
              <p className="text-[10px] text-slate-400 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={logout}
            aria-label="Logout"
            title="Log Out"
            className="text-slate-400 hover:text-red-400 p-1.5 rounded-lg hover:bg-surface-800 transition-colors cursor-pointer"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  )
}
