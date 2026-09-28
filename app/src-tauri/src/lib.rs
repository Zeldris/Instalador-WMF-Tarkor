//! App de escritorio de Tarkor. En esta fase (0.1-0.3 de docs/05) expone al asistente el análisis
//! del equipo, los perfiles y `config.json`. La gestión de los sidecars (backend y Ollama) llega en
//! las fases 0.4 y 0.5.

use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::equipo::{self, Equipo};
use tarkor_nucleo::perfiles::{self, Evaluacion};
use tauri::State;

#[tauri::command]
fn rutas(rutas: State<'_, Rutas>) -> Rutas {
    rutas.inner().clone()
}

#[tauri::command]
fn cargar_config(rutas: State<'_, Rutas>) -> Config {
    Config::cargar(&rutas.datos)
}

#[tauri::command]
fn guardar_config(rutas: State<'_, Rutas>, config: Config) -> Result<(), String> {
    config.guardar(&rutas.datos).map_err(|e| e.to_string())
}

/// Solo se llama tras el permiso explícito del jugador (pantalla 3 del asistente).
#[tauri::command]
async fn analizar_equipo(rutas: State<'_, Rutas>) -> Result<Equipo, String> {
    let datos = rutas.datos.clone();
    tauri::async_runtime::spawn_blocking(move || equipo::analizar(&datos))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn evaluar_perfiles(equipo: Option<Equipo>) -> Evaluacion {
    perfiles::evaluar(equipo.as_ref())
}

pub fn run() {
    tauri::Builder::default()
        .manage(Rutas::del_sistema())
        .invoke_handler(tauri::generate_handler![
            rutas,
            cargar_config,
            guardar_config,
            analizar_equipo,
            evaluar_perfiles
        ])
        .run(tauri::generate_context!())
        .expect("no se pudo iniciar Tarkor");
}
