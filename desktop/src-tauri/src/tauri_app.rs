use std::sync::Mutex;

use once_cell::sync::Lazy;
use tauri::Manager;
use tauri_plugin_store::StoreExt;

/// Global connection status tracker
pub static CONNECTION_STATUS: Lazy<Mutex<ConnectionStatus>> = Lazy::new(|| {
    Mutex::new(ConnectionStatus::Checking)
});

#[derive(Debug, Clone, PartialEq)]
pub enum ConnectionStatus {
    Checking,
    Connected,
    Disconnected,
    AuthError,
}

impl std::fmt::Display for ConnectionStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConnectionStatus::Checking => write!(f, "Checking..."),
            ConnectionStatus::Connected => write!(f, "Connected"),
            ConnectionStatus::Disconnected => write!(f, "Disconnected"),
            ConnectionStatus::AuthError => write!(f, "Auth Error"),
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .setup(|app| {
            let store = app.store("settings.json")?;

            // Check if this is first run (no server URL configured)
            let has_server_url = store.get("serverUrl").is_some();

            let main_window = app.get_webview_window("main").unwrap();

            if !has_server_url {
                // Show settings page on first run
                main_window.eval(r#"
                    document.getElementById('settingsPage').style.display = 'flex';
                    document.getElementById('mainFrame').style.display = 'none';
                "#).ok();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            check_connection,
            navigate_to_server,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
async fn get_settings(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    
    let server_url = store
        .get("serverUrl")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    
    let api_key = store
        .get("apiKey")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    
    Ok(serde_json::json!({
        "serverUrl": server_url,
        "apiKey": api_key,
    }))
}

#[tauri::command]
async fn save_settings(
    app: tauri::AppHandle,
    server_url: String,
    api_key: String,
) -> Result<(), String> {
    let mut store = app.store("settings.json").map_err(|e| e.to_string())?;
    
    store.set("serverUrl", server_url.into());
    store.set("apiKey", api_key.into());
    app.save_store(Some("settings.json".to_string()), &store)
        .map_err(|e| e.to_string())?;
    
    Ok(())
}

#[tauri::command]
async fn check_connection(server_url: String, api_key: String) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::new();
    
    let url = format!("{}/api/health", server_url.trim_end_matches('/'));
    
    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", api_key))
        .send()
        .await
        .map_err(|e| {
            let mut status = CONNECTION_STATUS.lock().unwrap();
            *status = ConnectionStatus::Disconnected;
            e.to_string()
        })?;
    
    if response.status().is_success() {
        let mut status = CONNECTION_STATUS.lock().unwrap();
        *status = ConnectionStatus::Connected;
        
        let body: serde_json::Value = response
            .json()
            .await
            .unwrap_or(serde_json::json!({"status": "ok"}));
        
        Ok(body)
    } else if response.status() == 401 {
        let mut status = CONNECTION_STATUS.lock().unwrap();
        *status = ConnectionStatus::AuthError;
        Err("Authentication failed. Check your API key.".to_string())
    } else {
        let mut status = CONNECTION_STATUS.lock().unwrap();
        *status = ConnectionStatus::Disconnected;
        Err(format!("Server returned status {}", response.status()))
    }
}

#[tauri::command]
async fn navigate_to_server(
    app: tauri::AppHandle,
    server_url: String,
    api_key: String,
) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("Main window not found".to_string())?;
    
    let clean_url = server_url.trim_end_matches('/').to_string();
    
    // Navigate the WebView directly to the server URL
    // This avoids iframe cross-origin issues entirely
    window
        .navigate(clean_url.parse().map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    
    // After navigation, inject the API key as a cookie for the remote origin.
    // We use eval() to set the cookie in the context of the loaded page,
    // so it's scoped to the server's origin.
    let inject_cookie = format!(
        r#"document.cookie = "hub_api_key={}; path=/; SameSite=Lax";"#,
        api_key
    );
    window.eval(&inject_cookie).ok();
    
    Ok(())
}
