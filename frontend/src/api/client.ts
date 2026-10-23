import { useAuthStore } from '../store/authStore'
import {
  User,
  TokenResponse,
  DocumentFile,
  FileUploadResponse,
  ChatSession,
  ChatMessage,
} from '../types'

const BASE_URL = ''

let isRefreshing = false
let refreshSubscribers: ((token: string) => void)[] = []

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token))
  refreshSubscribers = []
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const { accessToken, refreshToken, logout, setTokens } = useAuthStore.getState()

  const headers = new Headers(options.headers || {})

  // Set default Content-Type for JSON unless sending FormData
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  // Automatic Bearer token injection
  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const config: RequestInit = {
    ...options,
    headers,
  }

  let response = await fetch(`${BASE_URL}${endpoint}`, config)

  // Silent token refresh on 401
  if (
    response.status === 401 &&
    !endpoint.includes('/api/v1/auth/login') &&
    !endpoint.includes('/api/v1/auth/refresh')
  ) {
    if (!refreshToken) {
      logout()
      throw new Error('Session expired. Please log in again.')
    }

    if (!isRefreshing) {
      isRefreshing = true

      try {
        const refreshResponse = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })

        if (!refreshResponse.ok) {
          throw new Error('Refresh token invalid or expired')
        }

        const data: TokenResponse = await refreshResponse.json()
        setTokens(data.access_token, data.refresh_token, data.user)
        isRefreshing = false
        onRefreshed(data.access_token)

        // Retry original request with newly acquired token
        headers.set('Authorization', `Bearer ${data.access_token}`)
        response = await fetch(`${BASE_URL}${endpoint}`, {
          ...options,
          headers,
        })
      } catch (err) {
        isRefreshing = false
        refreshSubscribers = []
        logout()
        throw err
      }
    } else {
      // Wait for the in-progress refresh to finish
      const retryToken = await new Promise<string>((resolve) => {
        subscribeTokenRefresh((token) => resolve(token))
      })

      headers.set('Authorization', `Bearer ${retryToken}`)
      response = await fetch(`${BASE_URL}${endpoint}`, {
        ...options,
        headers,
      })
    }
  }

  if (!response.ok) {
    let errorDetail = 'An error occurred'
    try {
      const errJson = await response.json()
      errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson)
    } catch {
      errorDetail = await response.text()
    }
    throw new Error(errorDetail || `HTTP Error ${response.status}`)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T
  }

  return response.json()
}

// Typed API modules
export const authApi = {
  login: async (email: string, password: string): Promise<TokenResponse> => {
    return apiClient<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },

  register: async (
    email: string,
    password: string,
    fullName?: string,
    customSystemPrompt?: string
  ): Promise<User> => {
    return apiClient<User>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        full_name: fullName || null,
        custom_system_prompt: customSystemPrompt || null,
      }),
    })
  },

  logout: async (refreshToken: string): Promise<{ message: string }> => {
    return apiClient<{ message: string }>('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  },
}

export const usersApi = {
  getMe: async (): Promise<User> => {
    return apiClient<User>('/api/v1/users/me')
  },

  updateSettings: async (settings: {
    full_name?: string
    custom_system_prompt?: string
    password?: string
  }): Promise<User> => {
    return apiClient<User>('/api/v1/users/me/settings', {
      method: 'PATCH',
      body: JSON.stringify(settings),
    })
  },
}

export const filesApi = {
  list: async (): Promise<DocumentFile[]> => {
    return apiClient<DocumentFile[]>('/api/v1/files')
  },

  upload: async (file: File): Promise<FileUploadResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient<FileUploadResponse>('/api/v1/files/upload', {
      method: 'POST',
      body: formData,
    })
  },

  delete: async (fileId: string): Promise<{ message: string; file_id: string }> => {
    return apiClient<{ message: string; file_id: string }>(`/api/v1/files/${fileId}`, {
      method: 'DELETE',
    })
  },

  getStatusStreamUrl: (token?: string): string => {
    const currentToken = token || useAuthStore.getState().accessToken
    return `/api/v1/files/status-stream${currentToken ? `?token=${encodeURIComponent(currentToken)}` : ''}`
  },
}

export const chatApi = {
  listSessions: async (): Promise<ChatSession[]> => {
    return apiClient<ChatSession[]>('/api/v1/chat/sessions')
  },

  createSession: async (title?: string): Promise<ChatSession> => {
    return apiClient<ChatSession>('/api/v1/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(title ? { title } : {}),
    })
  },

  getSessionMessages: async (sessionId: string): Promise<ChatMessage[]> => {
    return apiClient<ChatMessage[]>(`/api/v1/chat/sessions/${sessionId}/messages`)
  },

  deleteSession: async (sessionId: string): Promise<{ message: string; session_id: string }> => {
    return apiClient<{ message: string; session_id: string }>(
      `/api/v1/chat/sessions/${sessionId}`,
      {
        method: 'DELETE',
      }
    )
  },
}
