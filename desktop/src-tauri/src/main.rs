#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod tauri_app;

fn main() {
    tauri_app::run()
}
