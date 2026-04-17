import { Navigate } from 'react-router-dom'
import { useAuthContext } from '../../stores/AuthContext'

export default function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, role } = useAuthContext()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (role !== 'admin') return <Navigate to="/dashboard" replace />
  return <>{children}</>
}
