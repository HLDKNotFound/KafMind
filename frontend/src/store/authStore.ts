import { create } from 'zustand'
import { User } from '../types'

interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  setTokens: (accessToken: string, refreshToken: string, user?: User) => void
  setUser: (user: User) => void
  logout: () => void
}

const ACCESS_KEY = 'kafmind_access_token'
const REFRESH_KEY = 'kafmind_refresh_token'
const USER_KEY = 'kafmind_user'

const getStoredItem = (key: string): string | null => {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

const getStoredUser = (): User | null => {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set) => {
  const initialAccessToken = getStoredItem(ACCESS_KEY)
  const initialRefreshToken = getStoredItem(REFRESH_KEY)
  const initialUser = getStoredUser()

  return {
    user: initialUser,
    accessToken: initialAccessToken,
    refreshToken: initialRefreshToken,
    isAuthenticated: Boolean(initialAccessToken),
    isLoading: false,

    setTokens: (accessToken: string, refreshToken: string, user?: User) => {
      try {
        localStorage.setItem(ACCESS_KEY, accessToken)
        localStorage.setItem(REFRESH_KEY, refreshToken)
        if (user) {
          localStorage.setItem(USER_KEY, JSON.stringify(user))
        }
      } catch {
        // ignore storage errors
      }

      set((state) => ({
        accessToken,
        refreshToken,
        user: user || state.user,
        isAuthenticated: true,
      }))
    },

    setUser: (user: User) => {
      try {
        localStorage.setItem(USER_KEY, JSON.stringify(user))
      } catch {
        // ignore storage errors
      }
      set({ user })
    },

    logout: () => {
      try {
        localStorage.removeItem(ACCESS_KEY)
        localStorage.removeItem(REFRESH_KEY)
        localStorage.removeItem(USER_KEY)
      } catch {
        // ignore
      }
      set({
        user: null,
        accessToken: null,
        refreshToken: null,
        isAuthenticated: false,
      })
    },
  }
})
