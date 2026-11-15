//! Comandos de datos del jugador, informe y comprobaciones: borrar datos, uso de la IA, «Copiar informe».

use crate::estado::*;
use crate::motor_ciclo::*;
use serde::Serialize;
use std::fs;
use tarkor_nucleo::desinstalar;
use tarkor_nucleo::informe::{self, EstadoMotor};
use tarkor_nucleo::ollama::{self, resumen_uso, tiene, Cargado, Uso};
use tarkor_nucleo::rendimiento::{self};
use tarkor_nucleo::{motor, rendimiento::hilos_para_ia};
use tauri::Manager;

/// Qué enseña el diálogo «Borrar datos del juego» (`INS-45`): la carpeta de la IA y su tamaño ya
/// formateado como en el desinstalador de Windows ("9,6 GB"; vacío si no hay nada).
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InfoBorrado {
    ruta_ia: String,
    tamano: String,
}

/// En qué sistema corre la app (`linux`, `windows`, `macos`): el frontal enseña «Borrar datos del
/// juego» solo en Linux, donde no hay desinstalador.
#[tauri::command]
pub(crate) fn plataforma() -> &'static str {
    std::env::consts::OS
}

#[tauri::command]
pub(crate) async fn info_borrado(app: tauri::AppHandle) -> Res<InfoBorrado> {
    tauri::async_runtime::spawn_blocking(move || {
        let estado = app.state::<Estado>();
        let info = desinstalar::info(&estado.rutas, &estado.config());
        InfoBorrado { ruta_ia: info.ruta_ia.display().to_string(), tamano: desinstalar::texto_gb(info.bytes_ia) }
    })
    .await
    .map_err(|e| e.to_string())
}

/// «Borrar datos del juego» (Linux, `INS-45`): para el motor y borra como el desinstalador de Windows
/// (los registros siempre; las partidas y la IA si se piden). Sin `Ocupado` cogido no se borra: un
/// cambio de perfil o una reparación a medias dejarían archivos a medio escribir.
#[tauri::command]
pub(crate) async fn borrar_datos(app: tauri::AppHandle, partidas: bool, ia: bool) -> Res<()> {
    let estado = app.state::<Estado>();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    let turno = estado.arranque.coger().await;
    let parado = estado.sacar_motor(&turno);
    let en_marcha = parado.is_some();
    if let Some(mut p) = parado {
        p.parar();
    }
    let app2 = app.clone();
    let borrado = tauri::async_runtime::spawn_blocking(move || {
        let estado = app2.state::<Estado>();
        desinstalar::borrar(&estado.rutas, &estado.config(), partidas, ia).map_err(|e| desinstalar::mensaje_error(&e))
    })
    .await
    .map_err(|e| e.to_string())
    .and_then(|r| r);
    if borrado.is_err() && en_marcha {
        // La app sigue abierta: el motor vuelve a estar en marcha. Con éxito se cierra y no hace falta.
        rearrancar_o_avisar(&app, &turno).await;
    }
    borrado
}

/// «Cerrar Tarkor» de la pantalla final de «Borrar datos del juego»: sale por el camino normal, que
/// también para el motor si lo hubiera.
#[tauri::command]
pub(crate) fn cerrar_app(app: tauri::AppHandle) {
    app.exit(0);
}

/// Dónde corre la IA ahora mismo (`/api/ps`). Error si el motor no está en marcha.
#[tauri::command]
pub(crate) async fn uso_ia(app: tauri::AppHandle) -> Res<Uso> {
    let cliente = app.state::<Estado>().cliente()?;
    let cargados = tauri::async_runtime::spawn_blocking(move || cliente.cargados())
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    Ok(resumen_uso(&cargados))
}

/// El texto de «Copiar informe» (docs/11), con la carpeta personal cambiada por `~`.
#[tauri::command]
pub(crate) async fn informe(app: tauri::AppHandle) -> Res<String> {
    tauri::async_runtime::spawn_blocking(move || {
        let estado = app.state::<Estado>();
        let config = estado.config();
        let perfil = config.perfil.as_deref().and_then(|id| estado.catalogo.perfil(id));
        let ajustes =
            perfil.map(|p| rendimiento::calcular(&estado.catalogo, p, config.equipo.as_ref(), config.uso_cpu));
        let cliente = estado.cliente();
        let version = cliente.as_ref().ok().and_then(|c| c.version().ok());
        let ps: Res<Vec<Cargado>> = cliente.and_then(|c| c.cargados().map_err(|e| e.to_string()));
        let registro = informe::ultimas_lineas(&estado.rutas.registros.join(REGISTRO_MOTOR), informe::LINEAS_REGISTRO);
        let ultimo = estado.ultimo_motivo_parada.bloquear().clone();
        let motor = EstadoMotor {
            version_catalogo: &estado.catalogo.motor.version,
            version_en_marcha: version.as_deref(),
            instalado: estado.ollama_externo.is_some()
                || motor::instalado(&config.ia_efectiva(&estado.rutas), &estado.catalogo.motor),
            en_marcha: version.is_some(),
            externo: estado.ollama_externo.is_some(),
            ultimo_motivo_parada: ultimo.as_deref(),
        };
        let sistema = format!("{} {}", std::env::consts::OS, std::env::consts::ARCH);
        let datos = informe::Datos {
            version_app: env!("CARGO_PKG_VERSION"),
            sistema: &sistema,
            equipo: config.equipo.as_ref(),
            perfil: config.perfil.as_deref(),
            uso_cpu: config.uso_cpu,
            ajustes: ajustes.as_ref(),
            origen_catalogo: &estado.origen_catalogo,
            motor,
            ps: ps.as_ref().map(Vec::as_slice).map_err(String::as_str),
            registro: &registro,
        };
        informe::componer(&datos, &informe::carpeta_personal().unwrap_or_default(), &config.ia_efectiva(&estado.rutas))
    })
    .await
    .map_err(|e| e.to_string())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase", tag = "resultado")]
pub(crate) enum Comprobacion {
    Ok {
        detalle: String,
    },
    /// Todavía no aplica en esta fase (llega con el juego empaquetado, fase 4).
    Omitida {
        motivo: String,
    },
}

/// Una de las comprobaciones de docs/07, por id.
#[tauri::command]
pub(crate) async fn comprobar(app: tauri::AppHandle, id: String) -> Res<Comprobacion> {
    let estado = app.state::<Estado>();
    let pendiente = || Ok(Comprobacion::Omitida { motivo: "Llega con el juego empaquetado (fase 4).".into() });
    match id.as_str() {
        "datos" => {
            let prueba = estado.rutas.datos.join(".prueba-escritura");
            fs::create_dir_all(&estado.rutas.datos)
                .and_then(|_| fs::write(&prueba, b"ok"))
                .and_then(|_| fs::remove_file(&prueba))
                .map_err(|e| {
                    format!("No se puede escribir en la carpeta de datos ({}): {e}", estado.rutas.datos.display())
                })?;
            Ok(Comprobacion::Ok { detalle: format!("Se puede escribir en {}.", estado.rutas.datos.display()) })
        }
        "basedatos" | "juego" | "mundo" => pendiente(),
        "motor" => {
            let cliente = estado.cliente()?;
            let v = tauri::async_runtime::spawn_blocking(move || cliente.version())
                .await
                .map_err(|e| e.to_string())?
                .map_err(|e| e.to_string())?;
            Ok(Comprobacion::Ok { detalle: format!("En marcha (Ollama {v}).") })
        }
        "modelos" => {
            let perfil = estado.perfil(&estado.config())?.clone();
            let cliente = estado.cliente()?;
            let hay = tauri::async_runtime::spawn_blocking(move || cliente.modelos())
                .await
                .map_err(|e| e.to_string())?
                .map_err(|e| e.to_string())?;
            let faltan: Vec<&str> = perfil.modelos().into_iter().filter(|m| !tiene(&hay, m)).collect();
            if !faltan.is_empty() {
                return Err(format!("Faltan modelos: {}. Vuelve al paso de descarga.", faltan.join(", ")));
            }
            Ok(Comprobacion::Ok { detalle: "Todos presentes.".into() })
        }
        "narracion" => {
            let config = estado.config();
            let perfil = estado.perfil(&config)?.clone();
            let piensa = estado.catalogo.modelos.get(&perfil.narrador).is_some_and(|m| m.piensa);
            let hilos = hilos_para_ia(config.uso_cpu, config.equipo.as_ref().map_or(4, |e| e.hilos));
            let cliente = estado.cliente()?;
            let prueba = tauri::async_runtime::spawn_blocking(move || cliente.probar(&perfil.narrador, piensa, hilos))
                .await
                .map_err(|e| e.to_string())?
                .map_err(|e: ollama::Error| e.to_string())?;
            Ok(Comprobacion::Ok {
                detalle: serde_json::json!({ "texto": prueba.texto, "tokensPorSegundo": prueba.tokens_por_segundo })
                    .to_string(),
            })
        }
        otro => Err(format!("comprobación desconocida: {otro}")),
    }
}
