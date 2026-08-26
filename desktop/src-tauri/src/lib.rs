use serde::Serialize;
use std::net::TcpListener;
use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeConfig {
    api_base_url: String,
    desktop_token: String,
}

struct DesktopRuntimeState {
    config: DesktopRuntimeConfig,
    sidecar: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn desktop_runtime_config(state: tauri::State<'_, DesktopRuntimeState>) -> DesktopRuntimeConfig {
    state.config.clone()
}

fn reserve_loopback_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .expect("failed to reserve a loopback port")
        .port()
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![desktop_runtime_config])
        .setup(|app| {
            let port = reserve_loopback_port();
            let port_argument = port.to_string();
            let token = format!("{}{}", uuid::Uuid::new_v4(), uuid::Uuid::new_v4());
            let app_data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&app_data_dir)?;
            let database_path = app_data_dir.join("learnflow.db");
            // Reference sources are application data, never the user's linked
            // project workspace. Keep the cache and uploaded originals in
            // separate directories so GitHub/URL sources cannot pollute a
            // project folder.
            let source_cache_dir = app_data_dir.join("repo-files");
            let source_uploads_dir = app_data_dir.join("source-uploads");
            std::fs::create_dir_all(&source_cache_dir)?;
            std::fs::create_dir_all(&source_uploads_dir)?;
            let database_url = format!(
                "sqlite+aiosqlite:///{}",
                database_path.to_string_lossy().replace('\\', "/")
            );
            let settings_path = app_data_dir.join("settings.env");
            let command = app
                .shell()
                .sidecar("learnflow-backend")?
                .args(["--host", "127.0.0.1", "--port", port_argument.as_str()])
                .env("DESKTOP_MODE", "true")
                .env("DESKTOP_TOKEN", &token)
                .env("DATABASE_URL", database_url)
                .env("SOURCE_CACHE_DIR", source_cache_dir.to_string_lossy().as_ref())
                .env("REPO_FILES_DIR", source_cache_dir.to_string_lossy().as_ref())
                .env("SOURCE_UPLOADS_DIR", source_uploads_dir.to_string_lossy().as_ref())
                .env("LEARNFLOW_SETTINGS_PATH", settings_path.to_string_lossy().as_ref())
                .env(
                    "CORS_ORIGINS",
                    "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:5173",
                );
            let (_events, child) = command.spawn()?;
            app.manage(DesktopRuntimeState {
                config: DesktopRuntimeConfig {
                    api_base_url: format!("http://127.0.0.1:{port}/api"),
                    desktop_token: token,
                },
                sidecar: Mutex::new(Some(child)),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building LearnFlow desktop application");

    app.run(|handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            if let Some(child) = handle
                .state::<DesktopRuntimeState>()
                .sidecar
                .lock()
                .expect("sidecar lock poisoned")
                .take()
            {
                let _ = child.kill();
            }
        }
    });
}
