//! Ciclo de vida del motor de IA: instalar, arrancar (con su candado) y asegurar que corre.

use crate::estado::*;
use crate::vigilancia::*;
use std::collections::BTreeMap;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tarkor_nucleo::catalogo::Perfil;
use tarkor_nucleo::procesos::{self, Especificacion, Proceso};
use tarkor_nucleo::rendimiento::{self};
use tarkor_nucleo::{modelos, motor};
use tauri::ipc::Channel;
use tauri::Manager;

#[tauri::command]
pub(crate) async fn instalar_motor(app: tauri::AppHandle, canal: Channel<motor::Progreso>) -> Result<(), ErrorIa> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
        let _ = canal.send(motor::Progreso::Listo);
        return Ok(());
    }
    let (ia, m, cancelar) = (estado.ia(), estado.catalogo.motor.clone(), estado.cancelar.nueva());
    tauri::async_runtime::spawn_blocking(move || {
        motor::instalar(&ia, &m, &cancelar, &mut |p| {
            // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
            let _ = canal.send(p);
        })
        .map(|_| ())
        .map_err(ErrorIa::from)
    })
    .await
    .map_err(ErrorIa::from)?
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

/// Lo que hace `asegurar_motor`. Un fallo suelto de `version()` no reinicia un motor sano (`sigue_en_marcha`).
pub(crate) async fn asegurar(app: &tauri::AppHandle) -> Res<()> {
    asegurar_con(app, None).await
}

/// `asegurar`, arrancando (si hace falta) con `perfil` en vez del guardado: `cambiar_perfil` con el motor caído lo
/// arranca ya con el perfil nuevo, que es el que va a descargar (el viejo puede ser justo el que no cabía en memoria).
pub(crate) async fn asegurar_con(app: &tauri::AppHandle, perfil: Option<&Perfil>) -> Res<()> {
    let estado = app.state::<Estado>();
    let en_marcha = || async {
        let a = app.clone();
        tauri::async_runtime::spawn_blocking(move || a.state::<Estado>().sigue_en_marcha()).await.unwrap_or(false)
    };
    let Some(turno) = estado.arranque.turno_si_parado(en_marcha).await else {
        return Ok(());
    };
    arrancar_con_perfil(app, &turno, perfil).await
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
    arrancar_con_perfil(app, turno, None).await
}

/// El perfil con el que se arranca: el pedido o, sin él, el guardado.
pub(crate) fn perfil_de_arranque(pedido: Option<&Perfil>, guardado: impl FnOnce() -> Res<Perfil>) -> Res<Perfil> {
    pedido.cloned().map_or_else(guardado, Ok)
}

/// `arrancar_con_turno` con `perfil` en vez del guardado (sin guardarlo).
pub(crate) async fn arrancar_con_perfil(app: &tauri::AppHandle, turno: &Turno<'_>, perfil: Option<&Perfil>) -> Res<()> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        return Ok(());
    }
    if estado.cerrando.load(Ordering::SeqCst) {
        return Err(CERRANDO.into());
    }
    let config = estado.config();
    let ia = config.ia_efectiva(&estado.rutas);
    let perfil = perfil_de_arranque(perfil, || estado.perfil(&config).cloned())?;
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
    if estado.cerrando.load(Ordering::SeqCst) {
        // La salida no pudo coger el turno a tiempo: el motor recién arrancado se para aquí (`Drop`).
        drop(proceso);
        return Err(CERRANDO.into());
    }
    estado.poner_motor(proceso, turno);
    // Un motor nuevo y sano: el aviso de la parada anterior ya no vale.
    *estado.detenido.bloquear() = None;
    Ok(())
}

const CERRANDO: &str = "La app se está cerrando.";

/// Lo que espera la salida de la app a que acabe un arranque o una parada en marcha antes de seguir sin turno.
const PLAZO_SALIDA: Duration = Duration::from_secs(3);

/// Al cerrar la app (`RunEvent::Exit`), el motor se para siempre (docs/08: nada queda funcionando en segundo plano).
/// Marca `cerrando` y para el motor con el turno, esperando como mucho `PLAZO_SALIDA`. Si un arranque tiene el turno,
/// al acabar ve `cerrando` y para su motor; si la app sale antes, el sistema lo mata con ella (el Job Object en
/// Windows, `PR_SET_PDEATHSIG` en Linux).
pub(crate) fn parar_al_salir(estado: &Estado) {
    estado.cerrando.store(true, Ordering::SeqCst);
    estado.cancelar.todas();
    if let Some(turno) = estado.arranque.coger_antes_de(PLAZO_SALIDA) {
        if let Some(mut p) = estado.sacar_motor(&turno) {
            p.parar();
        }
    } else if let Ok(mut motor) = estado.motor.try_lock() {
        if let Some(mut p) = motor.take() {
            p.parar();
        }
    }
}

/// Vuelve a arrancar el motor tras un error; si no arranca, avisa de la parada. Quien llama ya tiene
/// `Estado::arranque` y pasa su `Turno`.
pub(crate) async fn rearrancar_o_avisar(app: &tauri::AppHandle, turno: &Turno<'_>) {
    if let Err(e) = arrancar_con_turno(app, turno).await {
        avisar_parada(app, e);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn perfil(id: &str) -> Perfil {
        let mut p = tarkor_nucleo::catalogo::Catalogo::incrustado().perfiles[0].clone();
        p.id = id.into();
        p
    }

    #[test]
    fn con_perfil_pedido_no_se_arranca_con_el_guardado() {
        // `cambiar_perfil` con el motor caído: aunque el guardado no sirva, arranca con el nuevo.
        let nuevo = perfil("ligero");
        let elegido = perfil_de_arranque(Some(&nuevo), || Err("el guardado no arranca".into()));
        assert_eq!(elegido.map(|p| p.id), Ok("ligero".to_string()));
        assert_eq!(perfil_de_arranque(None, || Ok(perfil("guardado"))).map(|p| p.id), Ok("guardado".to_string()));
    }
}
