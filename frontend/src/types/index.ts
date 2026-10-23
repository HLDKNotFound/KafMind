export interface User {
  id: string
  email: string
  full_name: string | null
  custom_system_prompt: string | null
  is_active: boolean
  is_superuser: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export type FileStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED'

export interface DocumentFile {
  id: string
  user_id: string
  filename: string
  file_path: string
  file_size: number
  mime_type: string
  status: FileStatus
  chunk_count: number
  error_message: string | null
  created_at: string
}

export interface FileUploadResponse {
  message: string
  file_id: string
  file: DocumentFile
}

export interface ChatSession {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface SourceCitation {
  file_id: string
  filename: string
  chunk_index: number
  score: number
  text: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sources: SourceCitation[]
  created_at: string
}

export interface AgentStepEvent {
  step: string
  status: 'started' | 'completed'
  decision?: string
  search_query?: string
  rewrite_count?: number
  docs_count?: number
}
