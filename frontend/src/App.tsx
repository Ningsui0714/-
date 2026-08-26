import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/auth/ProtectedRoute'
import Layout from './components/layout/Layout'
import { useAuth } from './contexts/AuthContext'
import AgentPage from './pages/AgentPage'
import CheckpointPage from './pages/CheckpointPage'
import ExercisePage from './pages/ExercisePage'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import MemoryGraphPage from './pages/MemoryGraphPage'
import ReviewPage from './pages/ReviewPage'
import ProfilePage from './pages/ProfilePage'
import ProjectPage from './pages/ProjectPage'
import RegisterPage from './pages/RegisterPage'
import SettingsPage from './pages/SettingsPage'
import DemoEntryPage from './pages/DemoEntryPage'
import WorkspaceFilePage from './pages/WorkspaceFilePage'
import WF03TaskPage from './pages/WF03TaskPage'
import PersonalizedLearningEntryPage from './pages/PersonalizedLearningEntryPage'
import LearningTaskPlanPage from './pages/LearningTaskPlanPage'
import LearningTaskUpstreamBridgePage from './pages/LearningTaskUpstreamBridgePage'
import { getDesktopRuntime } from './services/desktopRuntime'

function DevSettingsRoute() {
  const { user } = useAuth()
  return user?.is_dev_login || Boolean(getDesktopRuntime().apiBaseUrl) ? <SettingsPage /> : <Navigate to="/agent" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/demo" element={<DemoEntryPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/agent" replace />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/projects" element={<HomePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/memory" element={<MemoryGraphPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/settings" element={<DevSettingsRoute />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/projects/:projectId/checkpoints/:checkpointId" element={<CheckpointPage />} />
          <Route path="/projects/:projectId/checkpoints/:checkpointId/exercises" element={<ExercisePage />} />
          <Route path="/projects/:projectId/workspace" element={<WorkspaceFilePage />} />
          <Route path="/wf03/tasks/:taskCardId" element={<WF03TaskPage />} />
          <Route path="/learning-task-plans/:runId" element={<LearningTaskPlanPage />} />
          <Route path="/learning-task-conversion/upstream" element={<LearningTaskUpstreamBridgePage />} />
          <Route path="/personalized-learning/tasks/:taskCardId/knowledge/:knowledgeId" element={<PersonalizedLearningEntryPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/agent" replace />} />
    </Routes>
  )
}
