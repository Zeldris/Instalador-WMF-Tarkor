//! App de escritorio de Tarkor: expone al asistente el análisis del equipo, el catálogo, la
//! configuración y el motor de IA (instalación, arranque, modelos y comprobaciones). El backend
//! del juego se añadirá como segundo proceso en la fase 4 con el mismo gestor (`procesos`).

mod comandos_basicos;
mod comandos_datos;
mod comandos_ia;
mod desinstalacion_cli;
mod estado;
mod motor_ciclo;
mod vigilancia;

use comandos_basicos::*;
use comandos_datos::*;
use comandos_ia::*;
use estado::{Cancelar, Candado, Estado};
use motor_ciclo::*;
use std::sync::atomic::AtomicBool;
use std::sync::Mutex;
use std::time::Duration;
use tarkor_nucleo::catalogo::Catalogo;
use tarkor_nucleo::config::Rutas;
use tauri::{Manager, RunEvent};
use vigilancia::*;

pub fn run() {
    desinstalacion_cli::ejecutar_orden_de_desinstalacion();
    let rutas_app = Rutas::del_sistema();
    let (catalogo, origen) = Catalogo::cargar(&rutas_app.datos);
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(Estado {
            rutas: rutas_app,
            catalogo,
            origen_catalogo: origen,
            motor: Mutex::new(None),
            url_motor: Mutex::new(None),
            // Para pruebas y desarrollo: usar un Ollama ya en marcha en vez de instalar uno.
            ollama_externo: std::env::var("TARKOR_OLLAMA_URL").ok(),
            cancelar: Cancelar::default(),
            cerrando: AtomicBool::new(false),
            reparacion: Mutex::new(None),
            ocupado: AtomicBool::new(false),
            detenido: Mutex::new(None),
            ultimo_motivo_parada: Mutex::new(None),
            arranque: Candado::default(),
        })
        .invoke_handler(tauri::generate_handler![
            rutas,
            catalogo_activo,
            origen_catalogo,
            cargar_config,
            guardar_config,
            analizar_equipo,
            evaluar_perfiles,
            ajustes_rendimiento,
            estado_motor,
            cancelar_descargas,
            instalar_motor,
            iniciar_motor,
            asegurar_motor,
            cambiar_carpeta_ia,
            motor_detenido,
            reintentar_motor,
            descargar_modelos,
            calentar_narrador,
            cambiar_perfil,
            modelos_sobrantes,
            borrar_modelos,
            plataforma,
            info_borrado,
            borrar_datos,
            cerrar_app,
            uso_ia,
            informe,
            reparar,
            comprobar
        ])
        .build(tauri::generate_context!())
        .expect("no se pudo iniciar Tarkor");
    // Vigilancia de los procesos cada 2 s, cargue lo que cargue la ventana (docs/11).
    let vigilante = app.handle().clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(2));
        vigilar_una_vez(&vigilante);
    });
    app.run(|app, evento| {
        // Al cerrar, el motor se para siempre (docs/08: nada queda funcionando en segundo plano).
        if let RunEvent::Exit = evento {
            parar_al_salir(&app.state::<Estado>());
        }
    });
}
