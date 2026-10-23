import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  UploadCloud,
  FileText,
  Trash2,
  CheckCircle2,
  Clock,
  Loader2,
  AlertTriangle,
  X,
  CheckSquare,
  Square,
  Sparkles,
} from 'lucide-react'
import { DocumentFile } from '../types'
import { filesApi } from '../api/client'
import { useAuthStore } from '../store/authStore'

interface FileManagerProps {
  files: DocumentFile[]
  selectedFileIds: Set<string>
  onToggleSelectFile: (fileId: string) => void
  onSelectAllFiles: (selectAll: boolean) => void
  onDeleteFile: (fileId: string) => Promise<void>
  onFilesUpdated: () => void
  isOpen: boolean
  onClose: () => void
}

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md']

export const FileManager: React.FC<FileManagerProps> = ({
  files,
  selectedFileIds,
  onToggleSelectFile,
  onSelectAllFiles,
  onDeleteFile,
  onFilesUpdated,
  isOpen,
  onClose,
}) => {
  const token = useAuthStore((state) => state.accessToken)
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Listen to SSE /api/v1/files/status-stream for real-time file updates
  useEffect(() => {
    if (!token) return

    const streamUrl = filesApi.getStatusStreamUrl(token)
    let eventSource: EventSource | null = null

    try {
      eventSource = new EventSource(streamUrl)

      eventSource.addEventListener('status', (_e: MessageEvent) => {
        try {
          // Trigger file list refresh when backend completes chunking/indexing
          onFilesUpdated()
        } catch (err) {
          console.error('Error handling SSE status event:', err)
        }
      })

      eventSource.onerror = () => {
        // EventSource will automatically retry connecting
      }
    } catch (err) {
      console.warn('Failed to initialize EventSource:', err)
    }

    return () => {
      if (eventSource) {
        eventSource.close()
      }
    }
  }, [token, onFilesUpdated])

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleProcessFiles = useCallback(
    async (fileList: FileList | File[]) => {
      setUploadError(null)
      const validFiles: File[] = []

      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i]
        const ext = '.' + file.name.split('.').pop()?.toLowerCase()
        if (ALLOWED_EXTENSIONS.includes(ext)) {
          validFiles.push(file)
        }
      }

      if (validFiles.length === 0) {
        setUploadError('Only PDF, DOCX, TXT, and MD files are supported.')
        return
      }

      setIsUploading(true)
      try {
        for (const file of validFiles) {
          await filesApi.upload(file)
        }
        onFilesUpdated()
      } catch (err: unknown) {
        if (err instanceof Error) {
          setUploadError(err.message)
        } else {
          setUploadError('Failed to upload file(s).')
        }
      } finally {
        setIsUploading(false)
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    },
    [onFilesUpdated]
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleProcessFiles(e.dataTransfer.files)
    }
  }

  const allSelected = files.length > 0 && files.every((f) => selectedFileIds.has(f.id))

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="bg-surface-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-brand-500/10 border border-brand-500/20 flex items-center justify-center text-brand-400">
              <FileText className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Document Manager</h3>
              <p className="text-xs text-slate-400">
                Upload and select files to ground Agentic RAG responses
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-surface-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drag and Drop Upload Zone */}
        <div className="p-6 pb-2">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-200 ${
              isDragging
                ? 'border-brand-500 bg-brand-500/10 scale-[0.99]'
                : 'border-slate-750 hover:border-slate-600 bg-surface-950/50 hover:bg-surface-950'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md"
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  handleProcessFiles(e.target.files)
                }
              }}
            />

            <div className="flex flex-col items-center gap-2">
              <div className="w-12 h-12 rounded-full bg-surface-800 flex items-center justify-center text-brand-400 border border-slate-700">
                {isUploading ? (
                  <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
                ) : (
                  <UploadCloud className="w-6 h-6" />
                )}
              </div>
              <p className="text-sm font-medium text-slate-200">
                {isUploading
                  ? 'Uploading & dispatching to Kafka...'
                  : 'Click or drag documents here to upload'}
              </p>
              <p className="text-xs text-slate-400">Supports PDF, DOCX, TXT, MD</p>
            </div>
          </div>

          {uploadError && (
            <div className="mt-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{uploadError}</span>
            </div>
          )}
        </div>

        {/* Controls Bar */}
        <div className="px-6 py-2.5 flex items-center justify-between text-xs text-slate-400 border-b border-slate-800/80">
          <div className="flex items-center gap-2">
            <button
              onClick={() => onSelectAllFiles(!allSelected)}
              className="flex items-center gap-1.5 text-slate-300 hover:text-white transition-colors cursor-pointer"
            >
              {allSelected ? (
                <CheckSquare className="w-4 h-4 text-brand-400" />
              ) : (
                <Square className="w-4 h-4 text-slate-400" />
              )}
              <span>{allSelected ? 'Deselect All' : 'Select All'}</span>
            </button>
            <span>•</span>
            <span>
              {selectedFileIds.size > 0
                ? `${selectedFileIds.size} of ${files.length} selected for RAG`
                : 'No files scoped (all indexed docs used)'}
            </span>
          </div>
          <span className="text-[11px] text-slate-400 flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-brand-400" /> Auto-syncing status via SSE
          </span>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-6 pt-2 space-y-2">
          {files.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-500">
              No documents uploaded yet. Upload files above to ingest them into Qdrant.
            </div>
          ) : (
            files.map((file) => {
              const isSelected = selectedFileIds.has(file.id)
              return (
                <div
                  key={file.id}
                  className={`flex items-center justify-between p-3 rounded-xl border transition-all ${
                    isSelected
                      ? 'bg-brand-500/5 border-brand-500/30'
                      : 'bg-surface-950/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <button
                      type="button"
                      onClick={() => onToggleSelectFile(file.id)}
                      className="cursor-pointer text-slate-400 hover:text-white shrink-0"
                    >
                      {isSelected ? (
                        <CheckSquare className="w-4 h-4 text-brand-400" />
                      ) : (
                        <Square className="w-4 h-4 text-slate-400" />
                      )}
                    </button>

                    <div className="truncate flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-200 truncate">
                          {file.filename}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                        <span>{formatFileSize(file.file_size)}</span>
                        <span>•</span>
                        <span>{new Date(file.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 ml-3">
                    {/* Status Badge */}
                    {file.status === 'PENDING' && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse">
                        <Clock className="w-3 h-3" />
                        <span>Pending</span>
                      </span>
                    )}

                    {file.status === 'PROCESSING' && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        <span>Processing</span>
                      </span>
                    )}

                    {file.status === 'READY' && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Ready ({file.chunk_count} chunks)</span>
                      </span>
                    )}

                    {file.status === 'FAILED' && (
                      <span
                        title={file.error_message || 'Processing failed'}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20 cursor-help"
                      >
                        <AlertTriangle className="w-3 h-3" />
                        <span>Failed</span>
                      </span>
                    )}

                    {/* Delete File Button */}
                    <button
                      type="button"
                      aria-label="Delete file"
                      onClick={() => onDeleteFile(file.id)}
                      className="text-slate-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-surface-800 transition-colors cursor-pointer"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
