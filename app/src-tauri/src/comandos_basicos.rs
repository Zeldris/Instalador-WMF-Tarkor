//! Comandos de lectura y configuración: rutas, catálogo, config, análisis del equipo y perfiles.

use crate::estado::*;
use serde::Serialize;
use std::collections::BTreeMap;
use tarkor_nucleo::carpetas::espacio_libre_mb;
use tarkor_nucleo::catalogo::{Catalogo, Origen};
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::equipo::{self, Equipo};
use tarkor_nucleo::motor;
use tarkor_nucleo::perfiles::{self, Evaluacion, UsoCpu};
use tarkor_nucleo::rendimiento::{self, Ajustes};
use tauri::{Manager, State};

#[tauri::command]
pub(crate) fn rutas(estado: State<'_, Estado>) -> Rutas {
    Rutas { ia: estado.ia(), ..estado.rutas.clone() }
}

/// El catálogo activo (el externo válido o el incrustado), para pantallas que muestran lo que de verdad se descarga.
#[tauri::command]
pub(crate) fn catalogo_activo(estado: State<'_, Estado>) -> Catalogo {
    estado.catalogo.clone()
}

/// De dónde salió el catálogo (incrustado, externo, o externo inválido y por qué).
#[tauri::command]
pub(crate) fn origen_catalogo(estado: State<'_, Estado>) -> Origen {
    estado.origen_catalogo.clone()
}

#[tauri::command]
pub(crate) fn cargar_config(estado: State<'_, Estado>) -> Config {
    estado.config()
}

#[tauri::command]
pub(crate) fn guardar_config(estado: State<'_, Estado>, config: Config) -> Res<()> {
    config.guardar(&estado.rutas.datos).map_err(|e| e.to_string())
}

/// Solo se llama tras el permiso explícito del jugador (pantalla 3 del asistente).
#[tauri::command]
pub(crate) async fn analizar_equipo(estado: State<'_, Estado>) -> Res<Equipo> {
    let datos = estado.rutas.datos.clone();
    tauri::async_runtime::spawn_blocking(move || equipo::analizar(&datos)).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub(crate) fn evaluar_perfiles(estado: State<'_, Estado>, equipo: Option<Equipo>) -> Evaluacion {
    perfiles::evaluar(&estado.catalogo, equipo.as_ref(), espacio_libre_mb(&estado.ia()))
}

#[tauri::command]
pub(crate) fn ajustes_rendimiento(
    estado: State<'_, Estado>,
    perfil: String,
    equipo: Option<Equipo>,
    uso_cpu: UsoCpu,
) -> Res<Ajustes> {
    let p = estado.catalogo.perfil(&perfil).ok_or_else(|| format!("perfil desconocido: {perfil}"))?;
    Ok(rendimiento::calcular(&estado.catalogo, p, equipo.as_ref(), uso_cpu))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InfoMotor {
    version: String,
    instalado: bool,
    en_marcha: bool,
    descarga_gb: f64,
    /// Tamaño de cada modelo del catálogo, para mostrarlo antes de descargar.
    modelos_gb: BTreeMap<String, f64>,
}

/// `async` y con el trabajo en un hilo aparte: un comando síncrono de Tauri v2 corre en el hilo
/// principal, y `version()` es una llamada de red bloqueante: la ventana se congelaría.
#[tauri::command]
pub(crate) async fn estado_motor(app: tauri::AppHandle) -> Res<InfoMotor> {
    tauri::async_runtime::spawn_blocking(move || {
        let estado = app.state::<Estado>();
        let m = &estado.catalogo.motor;
        InfoMotor {
            version: m.version.clone(),
            instalado: estado.ollama_externo.is_some() || motor::instalado(&estado.ia(), m),
            en_marcha: estado.en_marcha(),
            descarga_gb: if estado.ollama_externo.is_some() { 0.0 } else { m.paquete().map_or(0.0, |p| p.descarga_gb) },
            modelos_gb: estado.catalogo.modelos.iter().map(|(k, v)| (k.clone(), v.descarga_gb)).collect(),
        }
    })
    .await
    .map_err(|e| e.to_string())
}

/// Pausa cualquier descarga en curso. Lo descargado se conserva para continuar.
#[tauri::command]
pub(crate) fn cancelar_descargas(estado: State<'_, Estado>) {
    estado.cancelar.todas();
}
