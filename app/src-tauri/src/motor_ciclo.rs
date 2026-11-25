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
    asegurar_con(app, None).await.map(|_| ())
}

/// `asegurar`, arrancando (si hace falta) con `perfil` en vez del guardado: `cambiar_perfil` con el motor caído lo
/// arranca ya con el perfil nuevo, que es el que va a descargar (el viejo puede ser justo el que no cabía en memoria).
/// Da `true` si ha arrancado el motor (estaba parado) y `false` si ya corría.
pub(crate) async fn asegurar_con(app: &tauri::AppHandle, perfil: Option<&Perfil>) -> Res<bool> {
    let estado = app.state::<Estado>();
    let en_marcha = || async {
        let a = app.clone();
        tauri::async_runtime::spawn_blocking(move || a.state::<Estado>().sigue_en_marcha()).await.unwrap_or(false)
    };
    let Some(turno) = estado.arranque.turno_si_parado(en_marcha).await else {
        return Ok(false);
    };
    arrancar_con_perfil(app, &turno, perfil).await.map(|()| true)
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
    } else if let Some(mut motor) = bloquear_antes_de(&estado.motor, PLAZO_SALIDA) {
        // Sin turno (p. ej. la vigilancia relanzando el motor): se espera al `Mutex`, acotado, para pararlo igualmente.
        if let Some(mut p) = motor.take() {
            p.parar();
        }
    }
}

/// El `Mutex`, esperando como mucho `plazo` (reintentos cortos de `try_lock`). Uno envenenado se da igual.
pub(crate) fn bloquear_antes_de<T>(m: &std::sync::Mutex<T>, plazo: Duration) -> Option<std::sync::MutexGuard<'_, T>> {
    let limite = std::time::Instant::now() + plazo;
    loop {
        match m.try_lock() {
            Ok(g) => return Some(g),
            Err(std::sync::TryLockError::Poisoned(e)) => return Some(e.into_inner()),
            Err(std::sync::TryLockError::WouldBlock) if std::time::Instant::now() >= limite => return None,
            Err(std::sync::TryLockError::WouldBlock) => std::thread::sleep(Duration::from_millis(20)),
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

    fn estado() -> Estado {
        let base = std::path::PathBuf::from("/nada/tarkor-pruebas");
        Estado {
            rutas: tarkor_nucleo::config::Rutas { ia: base.join("ia"), registros: base.join("registros"), datos: base },
            catalogo: tarkor_nucleo::catalogo::Catalogo::incrustado(),
            origen_catalogo: tarkor_nucleo::catalogo::Origen::Incrustado,
            motor: std::sync::Mutex::new(None),
            url_motor: std::sync::Mutex::new(None),
            ollama_externo: None,
            cancelar: Cancelar::default(),
            cerrando: std::sync::atomic::AtomicBool::new(false),
            reparacion: std::sync::Mutex::new(None),
            ocupado: std::sync::atomic::AtomicBool::new(false),
            detenido: std::sync::Mutex::new(None),
            ultimo_motivo_parada: std::sync::Mutex::new(None),
            arranque: Candado::default(),
        }
    }

    #[test]
    fn la_salida_espera_al_motor_cogido_por_la_vigilancia() {
        // La vigilancia relanza el motor con el `Mutex` cogido: la salida espera a soltarlo en vez de rendirse.
        let m = std::sync::Arc::new(std::sync::Mutex::new(1));
        let cogido = std::sync::Arc::new(std::sync::Barrier::new(2));
        let (m2, c2) = (m.clone(), cogido.clone());
        let hilo = std::thread::spawn(move || {
            let _g = m2.lock().unwrap();
            c2.wait();
            std::thread::sleep(Duration::from_millis(300));
        });
        cogido.wait();
        assert!(bloquear_antes_de(&m, Duration::from_secs(3)).is_some(), "espera a que se suelte");
        hilo.join().unwrap();
        let _g = m.lock().unwrap();
        let inicio = std::time::Instant::now();
        assert!(bloquear_antes_de(&m, Duration::from_millis(100)).is_none(), "con plazo, no se queda colgada");
        assert!(inicio.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn la_salida_no_espera_a_un_arranque_largo_y_lo_deja_marcado() {
        let estado = estado();
        let descarga = estado.cancelar.nueva();
        // Un arranque en marcha (hasta 30 s) tiene el turno: la salida no espera más que su plazo.
        let arrancando = tauri::async_runtime::block_on(estado.arranque.coger());
        let inicio = std::time::Instant::now();
        parar_al_salir(&estado);
        assert!(inicio.elapsed() < PLAZO_SALIDA + Duration::from_secs(2), "la salida no espera 30 s");
        assert!(estado.cerrando.load(Ordering::SeqCst), "el arranque que acabe después para su motor");
        assert!(descarga.load(Ordering::SeqCst), "las descargas en marcha se cancelan");
        drop(arrancando);
        // Con la app cerrándose, ningún arranque llega a poner motor (comprueba `cerrando` antes y después).
        assert!(estado.motor.bloquear().is_none());
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
