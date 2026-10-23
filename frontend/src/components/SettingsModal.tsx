import React, { useState, useEffect } from 'react'
import { X, Sparkles, User, Lock, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { usersApi } from '../api/client'
import { User as UserType } from '../types'
import { useAuthStore } from '../store/authStore'

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const { user, setUser } = useAuthStore()

  const [fullName, setFullName] = useState(user?.full_name || '')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [customPrompt, setCustomPrompt] = useState(user?.custom_system_prompt || '')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (user) {
      setFullName(user.full_name || '')
      setCustomPrompt(user.custom_system_prompt || '')
    }
  }, [user])

  if (!isOpen) return null

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(false)

    if (password && password.length < 8) {
      setError('Password must be at least 8 characters long.')
      return
    }

    if (password && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setIsLoading(true)

    try {
      const payload: {
        full_name?: string
        password?: string
        custom_system_prompt?: string
      } = {}

      if (fullName.trim() !== (user?.full_name || '')) {
        payload.full_name = fullName.trim()
      }

      if (customPrompt.trim() !== (user?.custom_system_prompt || '')) {
        payload.custom_system_prompt = customPrompt.trim()
      }

      if (password) {
        payload.password = password
      }

      const updatedUser: UserType = await usersApi.updateSettings(payload)
      setUser(updatedUser)
      setSuccess(true)
      setPassword('')
      setConfirmPassword('')
      setTimeout(() => {
        setSuccess(false)
        onClose()
      }, 1200)
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to update settings.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="bg-surface-900 border border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-white">Account & Preferences</h3>
            <p className="text-xs text-slate-400">Configure your profile and system instructions</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-surface-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSave} className="p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Settings updated successfully!</span>
            </div>
          )}

          {/* Full Name */}
          <div>
            <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1.5">
              Full Name
            </label>
            <div className="relative">
              <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                id="settingsFullName"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Ada Lovelace"
                className="w-full bg-surface-950 border border-slate-750 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all"
              />
            </div>
          </div>

          {/* Custom System Prompt */}
          <div>
            <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-brand-400" />
              <span>Custom System Prompt</span>
            </label>
            <p className="text-[11px] text-slate-400 mb-1.5">
              Injected into the LangGraph prompt template to customize DeepSeek's tone and style.
            </p>
            <textarea
              id="settingsCustomPrompt"
              rows={3}
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="e.g. You are a senior technical writer. Always structure your responses with clear markdown headers and cite specific sections from retrieved files..."
              className="w-full bg-surface-950 border border-slate-750 rounded-xl p-3 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all resize-none"
            />
          </div>

          {/* New Password (Optional) */}
          <div className="pt-2 border-t border-slate-800">
            <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1.5">
              Update Password (Optional)
            </label>
            <div className="space-y-2">
              <div className="relative">
                <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="password"
                  id="settingsNewPassword"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="New password (leave blank to keep unchanged)"
                  className="w-full bg-surface-950 border border-slate-750 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all"
                />
              </div>

              {password && (
                <div className="relative">
                  <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="password"
                    id="settingsConfirmPassword"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    className="w-full bg-surface-950 border border-slate-750 rounded-xl pl-10 pr-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="pt-4 flex items-center justify-end gap-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="bg-brand-600 hover:bg-brand-500 text-white font-medium px-4 py-2 rounded-xl text-sm transition-all duration-150 flex items-center gap-2 shadow-md shadow-brand-600/30 disabled:opacity-50 cursor-pointer"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <span>Save Changes</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
