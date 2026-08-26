# LearnFlow Desktop

This directory is the Tauri 2 shell for the existing React/Vite application.
It starts the packaged FastAPI sidecar on a random loopback port and generates
a fresh desktop token for every launch. The WebView has directory-picker
permission, but no broad filesystem permission; project file access is
validated again by the sidecar.

The browser keeps its HTTP-only cookie flow. Desktop login additionally uses
a bearer token returned only when the per-launch desktop token is valid; the
sidecar requires both tokens on subsequent bearer-authenticated requests.
The bearer is kept in WebView session storage and is discarded when the app
session ends.

## Local build

1. Install the backend dependencies and `desktop/requirements-build.txt`.
2. Install Rust and the Tauri 2 platform prerequisites.
3. Run `npm install` in `frontend/` and `desktop/`.
4. Run `npm run build:sidecar` in `desktop/`.
5. Run `npm run dev` or `npm run build` in `desktop/`.

The generated target-triple sidecar and Rust/Node build output are ignored by
Git. macOS signing, Windows signing, and store credentials are intentionally
outside this repository stage.

## macOS one-click app

After `npm run build` finishes on Apple Silicon, install the real Tauri app and
create a Desktop icon with:

```bash
cd desktop
bash scripts/install_macos_app.sh
```

The script installs `LearnFlow.app` into `~/Applications`, creates
`~/Desktop/LearnFlow.app` as a clickable entry, and launches the app. The app
starts its bundled FastAPI sidecar on a random loopback port; it does not open
the browser-based `start.sh` workflow. Existing app entries are moved to a
timestamped `.backup-*` path instead of being deleted.

## Internal packages

`.github/workflows/desktop-internal.yml` builds unsigned macOS and Windows
packages on GitHub-hosted runners and uploads each `bundle/` directory as a
workflow artifact. It first runs the workspace/Tutor/registry contract tests,
then the frontend build, PyInstaller sidecar build, and Tauri build. Run the
workflow manually for release candidates; direct pushes to `main` or `codex/**`
that touch desktop, backend, or frontend code also exercise the same matrix.
