import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { Login } from '../pages/Login'
import { Register } from '../pages/Register'
import { authApi } from '../api/client'
import { useAuthStore } from '../store/authStore'

vi.mock('../api/client', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  },
}))

describe('Auth Pages & Store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.getState().logout()
    localStorage.clear()
  })

  it('renders login form and authenticates user successfully', async () => {
    const mockTokenResponse = {
      access_token: 'fake-access-token',
      refresh_token: 'fake-refresh-token',
      token_type: 'bearer',
      user: {
        id: 'user-123',
        email: 'test@example.com',
        full_name: 'Test User',
        custom_system_prompt: null,
        is_active: true,
        is_superuser: false,
        created_at: new Date().toISOString(),
      },
    }

    vi.mocked(authApi.login).mockResolvedValueOnce(mockTokenResponse)

    render(
      <BrowserRouter>
        <Login />
      </BrowserRouter>
    )

    expect(screen.getByRole('heading', { name: /welcome back/i })).toBeInTheDocument()
    const emailInput = screen.getByPlaceholderText('name@example.com')
    const passwordInput = screen.getByPlaceholderText('••••••••')
    const submitBtn = screen.getByRole('button', { name: /sign in/i })

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } })
    fireEvent.change(passwordInput, { target: { value: 'secret123' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith('test@example.com', 'secret123')
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
      expect(useAuthStore.getState().accessToken).toBe('fake-access-token')
      expect(useAuthStore.getState().user?.email).toBe('test@example.com')
    })
  })

  it('shows error message on failed login', async () => {
    vi.mocked(authApi.login).mockRejectedValueOnce(new Error('Incorrect email or password'))

    render(
      <BrowserRouter>
        <Login />
      </BrowserRouter>
    )

    const emailInput = screen.getByPlaceholderText('name@example.com')
    const passwordInput = screen.getByPlaceholderText('••••••••')
    const submitBtn = screen.getByRole('button', { name: /sign in/i })

    fireEvent.change(emailInput, { target: { value: 'bad@example.com' } })
    fireEvent.change(passwordInput, { target: { value: 'wrongpass' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Incorrect email or password')
    })
  })

  it('validates password length on registration and registers successfully', async () => {
    const mockUser = {
      id: 'new-user-123',
      email: 'new@example.com',
      full_name: 'New Person',
      custom_system_prompt: 'Be concise',
      is_active: true,
      is_superuser: false,
      created_at: new Date().toISOString(),
    }

    vi.mocked(authApi.register).mockResolvedValueOnce(mockUser)
    vi.mocked(authApi.login).mockResolvedValueOnce({
      access_token: 'new-access-token',
      refresh_token: 'new-refresh-token',
      token_type: 'bearer',
      user: mockUser,
    })

    render(
      <BrowserRouter>
        <Register />
      </BrowserRouter>
    )

    expect(screen.getByRole('heading', { name: /create account/i })).toBeInTheDocument()

    const nameInput = screen.getByPlaceholderText('Ada Lovelace')
    const emailInput = screen.getByPlaceholderText('name@example.com')
    const passwordInput = screen.getByPlaceholderText(/min. 8 characters/i)
    const promptInput = screen.getByPlaceholderText(/bullet points/i)
    const submitBtn = screen.getByRole('button', { name: /create account/i })

    // Test password too short (<8)
    fireEvent.change(emailInput, { target: { value: 'new@example.com' } })
    fireEvent.change(passwordInput, { target: { value: 'short' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/at least 8 characters/i)
    })

    // Now valid password
    fireEvent.change(nameInput, { target: { value: 'New Person' } })
    fireEvent.change(passwordInput, { target: { value: 'longsecretpassword' } })
    fireEvent.change(promptInput, { target: { value: 'Be concise' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(authApi.register).toHaveBeenCalledWith(
        'new@example.com',
        'longsecretpassword',
        'New Person',
        'Be concise'
      )
      expect(authApi.login).toHaveBeenCalledWith('new@example.com', 'longsecretpassword')
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
    })
  })
})
