import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
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
import UsersAdminPage from './pages/admin/UsersAdminPage'
import AuditLogPage from './pages/admin/AuditLogPage'
import EmailsAdminPage from './pages/admin/EmailsAdminPage'
import MailboxesAdminPage from './pages/admin/MailboxesAdminPage'
import InfluencersAdminPage from './pages/admin/InfluencersAdminPage'
import ScrapeAdminPage from './pages/admin/ScrapeAdminPage'
import TemplatesAdminPage from './pages/admin/TemplatesAdminPage'
import AgentsMonitorPage from './pages/admin/AgentsMonitorPage'

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
              path="/admin/*"
              element={
                <RequireAdmin>
                  <AdminLayout>
                    <Outlet />
                  </AdminLayout>
                </RequireAdmin>
              }
            >
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<AdminOverviewPage />} />
              <Route path="users" element={<UsersAdminPage />} />
              <Route path="audit" element={<AuditLogPage />} />
              <Route path="emails" element={<EmailsAdminPage />} />
              <Route path="mailboxes" element={<MailboxesAdminPage />} />
              <Route path="influencers" element={<InfluencersAdminPage />} />
              <Route path="scrape" element={<ScrapeAdminPage />} />
              <Route path="templates" element={<TemplatesAdminPage />} />
              <Route path="agents" element={<AgentsMonitorPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </WebSocketProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
