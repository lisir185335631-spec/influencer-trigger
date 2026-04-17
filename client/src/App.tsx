import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './stores/AuthContext'
import { WebSocketProvider } from './stores/WebSocketContext'
import ProtectedRoute from './components/ProtectedRoute'
import MainLayout from './components/layout/MainLayout'
import AdminLayout from './components/admin/AdminLayout'
import RequireAdmin from './components/admin/RequireAdmin'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import ScrapePage from './pages/ScrapePage'
import ScrapeTaskDetailPage from './pages/ScrapeTaskDetailPage'
import EmailsPage from './pages/EmailsPage'
import CRMPage from './pages/CRMPage'
import TemplatesPage from './pages/TemplatesPage'
import MailboxesPage from './pages/MailboxesPage'
import FollowUpPage from './pages/FollowUpPage'
import TeamPage from './pages/TeamPage'
import SettingsPage from './pages/SettingsPage'
import ImportPage from './pages/ImportPage'
import InfluencerDetailPage from './pages/InfluencerDetailPage'
import HolidaysPage from './pages/HolidaysPage'
import AdminOverviewPage from './pages/admin/AdminOverviewPage'

const PROTECTED_ROUTES = [
  { path: '/dashboard', element: <DashboardPage /> },
  { path: '/import', element: <ImportPage /> },
  { path: '/scrape', element: <ScrapePage /> },
  { path: '/scrape/tasks/:taskId', element: <ScrapeTaskDetailPage /> },
  { path: '/emails', element: <EmailsPage /> },
  { path: '/crm', element: <CRMPage /> },
  { path: '/crm/:id', element: <InfluencerDetailPage /> },
  { path: '/templates', element: <TemplatesPage /> },
  { path: '/mailboxes', element: <MailboxesPage /> },
  { path: '/followup', element: <FollowUpPage /> },
  { path: '/holidays', element: <HolidaysPage /> },
  { path: '/team', element: <TeamPage /> },
  { path: '/settings', element: <SettingsPage /> },
]

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <WebSocketProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {PROTECTED_ROUTES.map(({ path, element }) => (
              <Route
                key={path}
                path={path}
                element={
                  <ProtectedRoute>
                    <MainLayout>{element}</MainLayout>
                  </ProtectedRoute>
                }
              />
            ))}
            <Route
              path="/admin/overview"
              element={
                <RequireAdmin>
                  <AdminLayout>
                    <AdminOverviewPage />
                  </AdminLayout>
                </RequireAdmin>
              }
            />
            <Route path="/admin" element={<Navigate to="/admin/overview" replace />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </WebSocketProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
