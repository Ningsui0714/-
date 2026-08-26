import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { AuthProvider } from './contexts/AuthContext'
import { initializeDesktopRuntime } from './services/desktopRuntime'

// Local monaco instance (instead of CDN loader) so that monaco-vim and the
// editor share the same module instance.
import * as monaco from 'monaco-editor'
import { loader } from '@monaco-editor/react'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

;(self as any).MonacoEnvironment = {
  getWorker: () => new editorWorker(),
}
loader.config({ monaco })

async function bootstrap() {
  await initializeDesktopRuntime()
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  )
}

void bootstrap()
