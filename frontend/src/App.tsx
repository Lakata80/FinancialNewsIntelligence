import { Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { AppShell } from './components/Layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { DebugPage } from './pages/DebugPage'

function App() {
  return (
    <Router>
      <AppShell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/debug" element={<DebugPage />} />
        </Routes>
      </AppShell>
    </Router>
  )
}

export default App
