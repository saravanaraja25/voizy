import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/auth/AuthContext'
import { AppShell } from '@/components/app-shell'
import { ThemeProvider } from '@/components/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AgentsPage } from '@/pages/agents'
import { AccountPage } from '@/pages/account'
import { InvitePage } from '@/pages/invite'
import { NotFoundPage } from '@/pages/not-found'
import { SettingsPage } from '@/pages/settings'
import { SetupPage } from '@/pages/setup'
import { TeamPage } from '@/pages/team'
import { SignInPage } from '@/pages/sign-in'

// The editor pulls in the LiveKit client; load it only when someone opens an agent.
const AgentEditorPage = lazy(() =>
  import('@/pages/agent-editor').then((m) => ({ default: m.AgentEditorPage })),
)

// One client per app instance (never module-level) so cached data cannot outlive its session.
const makeQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 15_000 } },
  })

function PageSpinner() {
  return (
    <div className="flex justify-center py-24" role="status" aria-label="Loading">
      <Loader2 className="text-muted-foreground size-6 animate-spin" />
    </div>
  )
}

function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') {
    return (
      <div className="flex min-h-svh items-center justify-center" role="status" aria-label="Loading">
        <Loader2 className="text-muted-foreground size-6 animate-spin" />
      </div>
    )
  }
  if (status === 'needsSetup') return <Navigate to="/setup" replace />
  if (status === 'signedOut') {
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />
  }
  return <AppShell />
}

export function App() {
  const [queryClient] = useState(makeQueryClient)
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TooltipProvider>
            <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
              <Routes>
                <Route path="/signin" element={<SignInPage />} />
                <Route path="/setup" element={<SetupPage />} />
                <Route path="/invite/:token" element={<InvitePage />} />
                <Route element={<RequireAuth />}>
                  <Route index element={<AgentsPage />} />
                  <Route
                    path="agents/:id"
                    element={
                      <Suspense fallback={<PageSpinner />}>
                        <AgentEditorPage />
                      </Suspense>
                    }
                  />
                  <Route path="team" element={<TeamPage />} />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route path="account" element={<AccountPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Routes>
            </BrowserRouter>
            <Toaster richColors closeButton />
          </TooltipProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
