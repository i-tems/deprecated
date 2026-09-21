import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AuthProvider } from '@/contexts/AuthContext'
import { CellProvider, useCell } from '@/contexts/CellContext'
import { DirectoryProvider } from '@/contexts/DirectoryContext'
import { FocusProvider } from '@/contexts/FocusContext'
import { AuthGate } from '@/components/AuthGate'
import { Layout } from '@/components/Layout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { isUserLevelPath } from '@/lib/userLevelPaths'
import Login from '@/pages/Login'
import CellSelect from '@/pages/CellSelect'
import Projects from '@/pages/Projects'
import ProjectDetail from '@/pages/ProjectDetail'
import Issues from '@/pages/Issues'
import IssueDetail from '@/pages/IssueDetail'
import Initiatives from '@/pages/Initiatives'
import InitiativeDetail from '@/pages/InitiativeDetail'
import Signals from '@/pages/Signals'
import Capabilities from '@/pages/Capabilities'
import Workspace from '@/pages/Workspace'
import Settings from '@/pages/Settings'
import Help from '@/pages/Help'

// 현재 cell 이 정해져 있는데 URL 쿼리에서 빠진 경로로 이동하면 ?cell=<id> 를 자동 보정.
// 탭마다 URL 이 독립이므로 헤더 주입(X-Cell-Id)도 탭별로 독립이다.
// user-level 경로(Inbox/Triage)는 제외 — aggregate 호출이라 cell 미부착이 정본.
function CellQuerySync() {
  const location = useLocation()
  const navigate = useNavigate()
  const { currentCell } = useCell()
  useEffect(() => {
    if (!currentCell) return
    if (isUserLevelPath(location.pathname)) return
    const params = new URLSearchParams(location.search)
    if (params.get('cell') === currentCell.cell_id) return
    params.set('cell', currentCell.cell_id)
    navigate(
      { pathname: location.pathname, search: `?${params.toString()}`, hash: location.hash },
      { replace: true },
    )
  }, [location.pathname, location.search, location.hash, currentCell, navigate])
  return null
}

function RootRedirect() {
  // 홈 = Workspace (Inbox·Deck·기대감 흐름을 한 페이지에).
  return <Navigate to="/workspace" replace />
}

function CellGate({ children }: { children: React.ReactNode }) {
  const { isLoading, needsSelection } = useCell()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  // user-level 경로(Inbox/Triage)는 cell 선택 없이 통과 — aggregate 호출.
  if (needsSelection && !isUserLevelPath(location.pathname)) {
    return <CellSelect />
  }

  return (
    <>
      <CellQuerySync />
      {children}
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthGate>
          <DirectoryProvider>
          <CellProvider>
            <FocusProvider>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route
                element={
                  <ProtectedRoute>
                    <CellGate>
                      <Layout />
                    </CellGate>
                  </ProtectedRoute>
                }
              >
                <Route path="/cells" element={<CellSelect />} />
                <Route path="/" element={<RootRedirect />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/projects/:projectId" element={<ProjectDetail />} />
                <Route path="/issues" element={<Issues />} />
                <Route path="/issues/:issueId" element={<IssueDetail />} />
                <Route path="/initiatives" element={<Initiatives />} />
                <Route path="/initiatives/:initiativeId" element={<InitiativeDetail />} />
                <Route path="/signals" element={<Signals />} />
                <Route path="/workspace" element={<Workspace />} />
                {/* Inbox·Deck 은 Workspace 패널로 흡수 — 구 경로는 리다이렉트(북마크 보존). Triage 는 폐기. */}
                <Route path="/inbox" element={<Navigate to="/workspace" replace />} />
                <Route path="/deck" element={<Navigate to="/workspace" replace />} />
                <Route path="/capabilities" element={<Capabilities />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/help" element={<Help />} />
              </Route>
            </Routes>
            </FocusProvider>
          </CellProvider>
          </DirectoryProvider>
        </AuthGate>
      </AuthProvider>
    </BrowserRouter>
  )
}

// rebuild trigger: rename PR #456 image build miss recovery
