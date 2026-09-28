//! App de escritorio de Tarkor. En esta fase (0.1-0.3 de docs/05) expone al asistente el análisis
//! del equipo, el catálogo de perfiles, los ajustes de rendimiento y `config.json`. La gestión de
//! los sidecars (backend y Ollama) llega en las fases 0.4 y 0.5.

use tarkor_nucleo::catalogo::{Catalogo, Origen};
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::equipo::{self, Equipo};
use tarkor_nucleo::perfiles::{self, Evaluacion, UsoCpu};
use tarkor_nucleo::rendimiento::{self, Ajustes};
use tauri::State;

struct Estado {
    rutas: Rutas,
    catalogo: Catalogo,
    origen_catalogo: Origen,
}

#[tauri::command]
fn rutas(estado: State<'_, Estado>) -> Rutas {
    estado.rutas.clone()
}

/// De dónde salió el catálogo (incrustado, externo, o externo inválido y por qué).
#[tauri::command]
fn origen_catalogo(estado: State<'_, Estado>) -> Origen {
    estado.origen_catalogo.clone()
}

#[tauri::command]
fn cargar_config(estado: State<'_, Estado>) -> Config {
    Config::cargar(&estado.rutas.datos)
}

#[tauri::command]
fn guardar_config(estado: State<'_, Estado>, config: Config) -> Result<(), String> {
    config.guardar(&estado.rutas.datos).map_err(|e| e.to_string())
}

/// Solo se llama tras el permiso explícito del jugador (pantalla 3 del asistente).
#[tauri::command]
async fn analizar_equipo(estado: State<'_, Estado>) -> Result<Equipo, String> {
    let datos = estado.rutas.datos.clone();
    tauri::async_runtime::spawn_blocking(move || equipo::analizar(&datos))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn evaluar_perfiles(estado: State<'_, Estado>, equipo: Option<Equipo>) -> Evaluacion {
    perfiles::evaluar(&estado.catalogo, equipo.as_ref())
}

#[tauri::command]
fn ajustes_rendimiento(estado: State<'_, Estado>, perfil: String, equipo: Option<Equipo>, uso_cpu: UsoCpu) -> Result<Ajustes, String> {
    let p = estado.catalogo.perfil(&perfil).ok_or_else(|| format!("perfil desconocido: {perfil}"))?;
    Ok(rendimiento::calcular(&estado.catalogo, p, equipo.as_ref(), uso_cpu))
}

pub fn run() {
    let rutas_app = Rutas::del_sistema();
    let (catalogo, origen) = Catalogo::cargar(&rutas_app.datos);
    tauri::Builder::default()
        .manage(Estado { rutas: rutas_app, catalogo, origen_catalogo: origen })
        .invoke_handler(tauri::generate_handler![
            rutas,
            origen_catalogo,
            cargar_config,
            guardar_config,
            analizar_equipo,
            evaluar_perfiles,
            ajustes_rendimiento
        ])
        .run(tauri::generate_context!())
        .expect("no se pudo iniciar Tarkor");
}
