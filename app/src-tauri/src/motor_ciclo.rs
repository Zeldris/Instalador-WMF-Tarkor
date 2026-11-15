//! Ciclo de vida del motor de IA: instalar, arrancar (con su candado) y asegurar que corre.

use crate::estado::*;
use crate::vigilancia::*;
use std::collections::BTreeMap;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tarkor_nucleo::procesos::{self, Especificacion, Proceso};
use tarkor_nucleo::rendimiento::{self};
use tarkor_nucleo::{modelos, motor};
use tauri::ipc::Channel;
use tauri::Manager;

#[tauri::command]
pub(crate) async fn instalar_motor(app: tauri::AppHandle, canal: Channel<motor::Progreso>) -> Result<(), ErrorIa> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        let _ = canal.send(motor::Progreso::Listo);
        return Ok(());
    }
    estado.cancelar.store(false, Ordering::Relaxed);
    let (ia, m, cancelar) = (estado.ia(), estado.catalogo.motor.clone(), estado.cancelar.clone());
    tauri::async_runtime::spawn_blocking(move || {
        motor::instalar(&ia, &m, &cancelar, &mut |p| {
            let _ = canal.send(p);
        })
        .map(|_| ())
        .map_err(ErrorIa::from)
    })
    .await
    .map_err(|e| ErrorIa::from(e.to_string()))?
}

/// Arranca Ollama con los ajustes del perfil y el equipo guardados (docs/12). Si ya estaba en
/// marcha lo reinicia, para aplicar un perfil nuevo.
#[tauri::command]
pub(crate) async fn iniciar_motor(app: tauri::AppHandle) -> Res<()> {
    arrancar_motor(&app).await
}

/// Arranca solo si el motor no está en marcha, sin reiniciar uno que ya corre (`iniciar_motor` sí lo haría). Lo usa el
/// juego al entrar (`INS-42`). Comprobar y arrancar van bajo el mismo candado que `arrancar_motor`: dos entradas
/// seguidas, o un cambio de perfil a la vez, no lanzan dos arranques. Con un Ollama externo no hace nada.
#[tauri::command]
pub(crate) async fn asegurar_motor(app: tauri::AppHandle) -> Res<()> {
    asegurar(&app).await
}

/// Lo que hace `asegurar_motor`; también lo usa `cambiar_perfil` para tener motor antes de descargar.
pub(crate) async fn asegurar(app: &tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    let en_marcha = || async {
        let a = app.clone();
        tauri::async_runtime::spawn_blocking(move || a.state::<Estado>().en_marcha()).await.unwrap_or(false)
    };
    let Some(turno) = estado.arranque.turno_si_parado(en_marcha).await else {
        return Ok(());
    };
    arrancar_con_turno(app, &turno).await
}

/// Lo que hace `iniciar_motor`. En fila con cualquier otro arranque: quien ya tenga `Estado::arranque` cogido usa
/// `arrancar_con_turno`.
pub(crate) async fn arrancar_motor(app: &tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    let turno = estado.arranque.coger().await;
    arrancar_con_turno(app, &turno).await
}

/// El arranque en sí: quien lo llama ya tiene `Estado::arranque`, y lo demuestra pasando su `Turno`.
pub(crate) async fn arrancar_con_turno(app: &tauri::AppHandle, turno: &Turno<'_>) -> Res<()> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        return Ok(());
    }
    let config = estado.config();
    let ia = config.ia_efectiva(&estado.rutas);
    let perfil = estado.perfil(&config)?.clone();
    let m = &estado.catalogo.motor;
    let ejecutable = motor::ejecutable(&motor::carpeta(&ia, m));
    if !ejecutable.exists() {
        return Err("El motor de IA no está instalado.".into());
    }
    let ajustes = rendimiento::calcular(&estado.catalogo, &perfil, config.equipo.as_ref(), config.uso_cpu);
    let puerto = procesos::puerto_libre().map_err(|e| e.to_string())?;
    let mut entorno: BTreeMap<String, String> = ajustes.ollama.into_iter().collect();
    entorno.insert("OLLAMA_HOST".into(), format!("127.0.0.1:{puerto}"));
    entorno.insert("OLLAMA_MODELS".into(), modelos::carpeta(&ia).to_string_lossy().into_owned());
    let espec = Especificacion {
        nombre: "El motor de IA".into(),
        programa: ejecutable,
        argumentos: vec!["serve".into()],
        entorno,
        registro: estado.rutas.registros.join(REGISTRO_MOTOR),
        puerto,
        ruta_salud: "/api/version".into(),
        espera_arranque: Duration::from_secs(30),
    };
    if let Some(mut viejo) = estado.sacar_motor(turno) {
        viejo.parar();
    }
    let proceso = tauri::async_runtime::spawn_blocking(move || Proceso::arrancar(espec))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    estado.poner_motor(proceso, turno);
    // Un motor nuevo y sano: el aviso de la parada anterior ya no vale.
    *estado.detenido.lock().unwrap() = None;
    Ok(())
}

/// Vuelve a arrancar el motor tras un error; si no arranca, avisa de la parada. Quien llama ya tiene
/// `Estado::arranque` y pasa su `Turno`.
pub(crate) async fn rearrancar_o_avisar(app: &tauri::AppHandle, turno: &Turno<'_>) {
    if let Err(e) = arrancar_con_turno(app, turno).await {
        avisar_parada(app, e);
    }
}
