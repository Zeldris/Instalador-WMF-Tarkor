//! Vigilancia del motor: avisos de parada (evento `motor-detenido`) y «Reintentar».

use crate::estado::*;
use crate::motor_ciclo::*;
use tarkor_nucleo::informe::{self};
use tarkor_nucleo::procesos::{self, MotorDetenido};
use tauri::{Emitter, Manager, State};

/// Guarda el aviso de motor detenido y lo emite como evento `motor-detenido`.
pub(crate) fn avisar_parada(app: &tauri::AppHandle, motivo: String) {
    let estado = app.state::<Estado>();
    let cola = informe::ultimas_lineas(&estado.rutas.registros.join(REGISTRO_MOTOR), informe::LINEAS_REGISTRO);
    // Solo el último arranque: una falta de memoria de uno anterior no cuenta.
    let aviso = MotorDetenido {
        motivo: motivo.clone(),
        sin_memoria: procesos::sin_memoria(procesos::desde_ultimo_arranque(&cola)),
    };
    *estado.ultimo_motivo_parada.lock().unwrap() = Some(motivo);
    *estado.detenido.lock().unwrap() = Some(aviso.clone());
    let _ = app.emit("motor-detenido", aviso);
}

/// Un paso de la vigilancia (cada 2 s): si el motor propio se ha detenido de verdad, avisa una vez.
/// Si el motor no está en el `Mutex` (nunca arrancó, es externo o una operación lo ha quitado a
/// propósito: Reparar, Mover, cambio de perfil, reintento) no hay nada que vigilar ni que avisar.
/// Se decide con el `Mutex` del motor cogido, para no cruzarse con un reintento.
///
/// Un reinicio automático tras una caída (`Proceso::vigilar`) puede tardar hasta 30 s con el
/// `Mutex` cogido; `cliente()` no lo usa (lee `url_motor`) y el relanzado conserva el puerto.
pub(crate) fn vigilar_una_vez(app: &tauri::AppHandle) {
    let estado = app.state::<Estado>();
    let mut motor = estado.motor.lock().unwrap();
    let Some(proceso) = motor.as_mut() else { return };
    let visto = proceso.vigilar();
    let ya_avisado = estado.detenido.lock().unwrap().is_some();
    if let Some(motivo) = procesos::aviso_nuevo(&visto, ya_avisado) {
        avisar_parada(app, motivo.to_string());
    }
}

/// El aviso de motor detenido pendiente, para que el frontal lo lea al montarse.
#[tauri::command]
pub(crate) fn motor_detenido(estado: State<'_, Estado>) -> Option<MotorDetenido> {
    estado.detenido.lock().unwrap().clone()
}

/// «Reintentar» de la pantalla «El motor se ha detenido»: saca el motor viejo del `Mutex`, borra el
/// aviso y vuelve a arrancar con `arrancar_con_turno` (puerto nuevo y config al día, hasta 30 s). Si
/// falla, se vuelve a guardar y emitir el aviso.
#[tauri::command]
pub(crate) async fn reintentar_motor(app: tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    let turno = estado.arranque.coger().await;
    // Primero se saca el proceso y luego se borra el aviso: la vigilancia no ve un motor caído sin
    // aviso y lo avisa otra vez mientras se reintenta.
    let viejo = estado.sacar_motor(&turno);
    *estado.detenido.lock().unwrap() = None;
    if let Some(mut v) = viejo {
        v.parar();
    }
    match arrancar_con_turno(&app, &turno).await {
        Ok(()) => Ok(()),
        Err(motivo) => {
            avisar_parada(&app, motivo.clone());
            Err(motivo)
        }
    }
}
