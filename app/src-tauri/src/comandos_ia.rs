//! Comandos de la IA que tocan carpeta, modelos o perfil: mover la carpeta, descargar, cambiar de perfil,
//! borrar sobrantes y reparar.

use crate::estado::*;
use crate::motor_ciclo::*;
use crate::vigilancia::*;
use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use tarkor_nucleo::carpetas::mover_carpeta;
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::ollama::{self, tiene, Cliente, ProgresoModelo};
use tarkor_nucleo::{modelos, motor};
use tauri::ipc::Channel;
use tauri::Manager;

/// Mueve la carpeta de la IA a `<destino>/Tarkor IA` (como la «SteamLibrary» que crea Steam
/// dentro de la carpeta elegida), guarda la nueva ruta en `config.json` y devuelve las rutas
/// efectivas. Para el motor mientras se mueve y, si estaba en marcha, lo arranca con la ruta
/// nueva; si el movimiento falla, lo deja como estaba. Si ya es esa carpeta, no hace nada; si se
/// elige una «Tarkor IA», se usa tal cual en vez de anidar otra.
///
/// Un error después de mover (el motor no arranca) llega con la carpeta ya cambiada y guardada:
/// el asistente vuelve a leer `config.json` y las rutas en cualquier error.
#[tauri::command]
pub(crate) async fn cambiar_carpeta_ia(app: tauri::AppHandle, destino: String) -> Res<Rutas> {
    let estado = app.state::<Estado>();
    let elegida = PathBuf::from(destino);
    let nueva = if elegida.file_name().is_some_and(|n| n == "Tarkor IA") { elegida } else { elegida.join("Tarkor IA") };
    let actual = estado.ia();
    if nueva == actual {
        return Ok(Rutas { ia: actual, ..estado.rutas.clone() });
    }
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    // Parar, mover y volver a arrancar, sin que `asegurar_motor` arranque un motor en mitad del movimiento.
    let turno = estado.arranque.coger().await;
    let parado = estado.sacar_motor(&turno);
    let en_marcha = parado.is_some();
    if let Some(mut p) = parado {
        p.parar();
    }
    let (origen, a) = (actual.clone(), nueva.clone());
    let movido = tauri::async_runtime::spawn_blocking(move || mover_carpeta(&origen, &a))
        .await
        .map_err(|e| e.to_string())
        .and_then(|r| r);
    if let Err(e) = movido {
        if en_marcha {
            rearrancar_o_avisar(&app, &turno).await;
        }
        return Err(e);
    }
    // Se vuelve a leer: lo que el asistente guardara durante la copia no se pisa.
    let mut config = estado.config();
    config.carpeta_ia = Some(nueva.clone());
    if let Err(e) = config.guardar(&estado.rutas.datos) {
        // Sin guardar, la próxima apertura buscaría la IA en la carpeta de antes: se devuelve allí.
        let (a, b) = (nueva.clone(), actual.clone());
        let vuelta = tauri::async_runtime::spawn_blocking(move || mover_carpeta(&a, &b))
            .await
            .map_err(|e| e.to_string())
            .and_then(|r| r);
        if en_marcha {
            rearrancar_o_avisar(&app, &turno).await;
        }
        return Err(match vuelta {
            Ok(_) => format!("No se pudo guardar el cambio ({e}); la carpeta sigue en {}.", actual.display()),
            Err(v) => format!("No se pudo guardar el cambio ({e}) ni devolver la carpeta a {}: {v}", actual.display()),
        });
    }
    if let Ok(Some(aviso)) = movido {
        eprintln!("{aviso}");
    }
    if en_marcha {
        if let Err(e) = arrancar_con_turno(&app, &turno).await {
            avisar_parada(&app, e.clone());
            return Err(format!("La carpeta se movió a {}, pero el motor de IA no arranca: {e}", nueva.display()));
        }
    }
    Ok(Rutas { ia: nueva, ..estado.rutas.clone() })
}

/// Baja los `modelos` que `cliente` aún no tiene, avisando por `canal`. Ollama reanuda lo que se
/// quedara a medias; `cancelar` corta la descarga en curso.
pub(crate) fn descargar_faltantes(
    cliente: &Cliente,
    modelos: &[String],
    cancelar: &AtomicBool,
    canal: &Channel<ProgresoModelo>,
) -> Result<(), ollama::Error> {
    let hay = cliente.modelos()?;
    for m in modelos {
        if tiene(&hay, m) {
            // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
            let _ = canal.send(ProgresoModelo { modelo: m.clone(), estado: "success".into(), hecho: 1, total: 1 });
            continue;
        }
        cliente.descargar_modelo(m, cancelar, &mut |p| {
            // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
            let _ = canal.send(p);
        })?;
    }
    Ok(())
}

/// Descarga los modelos del perfil que falten. Ollama reanuda lo que se quedara a medias.
#[tauri::command]
pub(crate) async fn descargar_modelos(
    app: tauri::AppHandle,
    canal: Channel<ProgresoModelo>,
) -> Result<Vec<String>, ErrorIa> {
    let estado = app.state::<Estado>();
    estado.cancelar.store(false, Ordering::Relaxed);
    let perfil = estado.perfil(&estado.config())?.clone();
    let cliente = estado.cliente()?;
    let cancelar = estado.cancelar.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let modelos: Vec<String> = perfil.modelos().into_iter().map(String::from).collect();
        descargar_faltantes(&cliente, &modelos, &cancelar, &canal)?;
        Ok(modelos)
    })
    .await
    .map_err(|e| ErrorIa::from(e.to_string()))?
}

/// Carga el narrador del perfil en memoria al entrar en el juego (`INS-42`, docs/12), para que el primer turno no
/// espere la carga. No arranca el motor: si no está en marcha falla, y el frontal lo arranca antes de llamar.
/// El error lleva `sin_memoria` cuando el motor no pudo cargar el modelo (pide un perfil más ligero).
#[tauri::command]
pub(crate) async fn calentar_narrador(app: tauri::AppHandle) -> Result<(), ErrorIa> {
    let estado = app.state::<Estado>();
    let narrador = estado.perfil(&estado.config())?.narrador.clone();
    let cliente = estado.cliente()?;
    tauri::async_runtime::spawn_blocking(move || cliente.calentar(&narrador))
        .await
        .map_err(|e| ErrorIa::from(e.to_string()))?
        .map_err(ErrorIa::from)
}

/// Cambia de perfil desde Ajustes (`INS-43`, docs/11): descarga con el motor en marcha lo que falte
/// del perfil nuevo y, solo si termina bien, guarda `perfil` y `modelos_descargados` y reinicia el
/// motor para que aplique los ajustes del perfil nuevo. Si la descarga falla o se cancela
/// (`cancelar_descargas`), el perfil de antes sigue guardado y activo, y el motor ni se toca. Si el
/// motor no arranca con el perfil nuevo, se vuelve al de antes. Con un Ollama externo descarga y
/// guarda, sin reiniciar nada. No coincide con Reparar, Mover ni borrar modelos.
#[tauri::command]
pub(crate) async fn cambiar_perfil(
    app: tauri::AppHandle,
    perfil: String,
    canal: Channel<ProgresoModelo>,
) -> Result<Config, ErrorIa> {
    let estado = app.state::<Estado>();
    let nuevo = estado.catalogo.perfil(&perfil).ok_or_else(|| format!("perfil desconocido: {perfil}"))?.clone();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    let antes = estado.config();
    if antes.perfil.as_deref() == Some(perfil.as_str()) {
        return Ok(antes);
    }
    estado.cancelar.store(false, Ordering::Relaxed);
    let modelos: Vec<String> = nuevo.modelos().into_iter().map(String::from).collect();
    if estado.ollama_externo.is_none() {
        // Tras una doble caída el `Proceso` sigue en el `Mutex` con el hijo muerto (o no hay
        // motor): sin motor vivo la descarga fallaría con un error de conexión, y «Cambiar a un
        // perfil más ligero» no serviría justo cuando se ofrece. Arrancar borra el aviso. Comprobar y arrancar van
        // bajo el candado de arranque, que se suelta antes de descargar (puede tardar horas).
        asegurar(&app).await?;
    }
    let cliente = estado.cliente()?;
    let (cancelar, lista) = (estado.cancelar.clone(), modelos.clone());
    // Sin pasar por `to_string`: así el frontal sabe si el corte fue de red y espera para reintentar (`INS-42`).
    tauri::async_runtime::spawn_blocking(move || descargar_faltantes(&cliente, &lista, &cancelar, &canal))
        .await
        .map_err(|e| e.to_string())??;
    // Se vuelve a leer: lo que el asistente guardara durante la descarga no se pisa.
    let mut config = estado.config();
    config.perfil = Some(perfil);
    config.modelos_descargados = modelos;
    // Guardar el perfil y reiniciar el motor con él, sin que `asegurar_motor` arranque uno con la config a medias.
    let turno = estado.arranque.coger().await;
    config
        .guardar(&estado.rutas.datos)
        .map_err(|e| ErrorIa::from(format!("No se pudo guardar el perfil nuevo ({e}); sigue el de antes.")))?;
    if estado.ollama_externo.is_none() {
        if let Err(e) = arrancar_con_turno(&app, &turno).await {
            // Sin motor con el perfil nuevo no se queda a medias: vuelve el de antes, con su motor.
            let mut vuelta = estado.config();
            vuelta.perfil = antes.perfil.clone();
            vuelta.modelos_descargados = antes.modelos_descargados.clone();
            let guardado = vuelta.guardar(&estado.rutas.datos);
            let vuelto = arrancar_con_turno(&app, &turno).await;
            if let Err(e2) = &vuelto {
                // Sin motor con ninguno de los dos perfiles: se avisa, para que salga la pantalla
                // «El motor se ha detenido» con su «Reintentar».
                avisar_parada(&app, e2.clone());
            }
            return Err(ErrorIa::from(match (guardado, vuelto) {
                (Ok(()), Ok(())) => format!("El motor de IA no arranca con el perfil nuevo ({e}); sigue el perfil de antes."),
                (Ok(()), Err(e2)) => format!("El motor de IA no arranca con el perfil nuevo ({e}) ni con el de antes ({e2}); el motor está detenido."),
                (Err(g), Ok(())) => format!("El motor de IA no arranca con el perfil nuevo ({e}) y no se pudo devolver el perfil de antes ({g})."),
                (Err(g), Err(e2)) => format!("El motor de IA no arranca con el perfil nuevo ({e}) ni con el de antes ({e2}), y no se pudo devolver el perfil de antes ({g}); el motor está detenido."),
            }));
        }
    }
    Ok(config)
}

/// Un modelo del Ollama propio que no es del perfil actual.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Sobrante {
    modelo: String,
    gb: f64,
}

/// Los modelos del Ollama propio que no son del perfil actual. Con un Ollama externo, ninguno: los
/// modelos del jugador no se tocan.
pub(crate) fn sobrantes_de(estado: &Estado) -> Res<Vec<(String, u64)>> {
    if estado.ollama_externo.is_some() {
        return Ok(Vec::new());
    }
    let perfil = estado.perfil(&estado.config())?.clone();
    let hay = estado.cliente()?.modelos_con_tamano().map_err(|e| e.to_string())?;
    Ok(ollama::sobrantes(hay, &perfil.modelos()))
}

#[tauri::command]
pub(crate) async fn modelos_sobrantes(app: tauri::AppHandle) -> Res<Vec<Sobrante>> {
    let lista = tauri::async_runtime::spawn_blocking(move || sobrantes_de(&app.state::<Estado>()))
        .await
        .map_err(|e| e.to_string())??;
    Ok(lista
        .into_iter()
        .map(|(modelo, bytes)| Sobrante { modelo, gb: (bytes as f64 / 1e9 * 100.0).round() / 100.0 })
        .collect())
}

/// Borra modelos sobrantes. Solo borra los que siguen siéndolo al llamar (se recalcula): nunca uno
/// del perfil, aunque el frontal tenga una lista vieja. Rechaza un Ollama externo.
#[tauri::command]
pub(crate) async fn borrar_modelos(app: tauri::AppHandle, modelos: Vec<String>) -> Res<()> {
    let estado = app.state::<Estado>();
    if estado.ollama_externo.is_some() {
        return Err("Los modelos de un Ollama externo no se tocan desde Tarkor.".into());
    }
    // Sin esto, un cambio de perfil a medias dejaría «sobrando» los modelos que acaba de bajar.
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    let app2 = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let estado = app2.state::<Estado>();
        let sobran = sobrantes_de(&estado)?;
        let cliente = estado.cliente()?;
        for (m, _) in sobran.iter().filter(|(m, _)| modelos.contains(m)) {
            cliente.borrar_modelo(m).map_err(|e| e.to_string())?;
        }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Reparacion {
    motor_reinstalado: bool,
    /// Capas de modelos dañadas o que faltaban, que `/api/pull` ha vuelto a bajar.
    capas_repuestas: usize,
    modelos: Vec<String>,
}

/// «Reparar» (`INS-49`, docs/11): para el motor, comprueba la suma de cada archivo suyo y lo
/// reinstala si hace falta; comprueba las capas de los modelos y borra las dañadas; arranca el
/// motor y pide todos los modelos del perfil con `/api/pull`, que solo baja lo que falta. Con un
/// Ollama externo solo se pide de nuevo cada modelo: ni su motor ni su carpeta son de la app.
/// Si falla después de parar el motor, lo vuelve a arrancar antes de devolver el error.
#[tauri::command]
pub(crate) async fn reparar(
    app: tauri::AppHandle,
    canal_motor: Channel<motor::Progreso>,
    canal: Channel<ProgresoModelo>,
) -> Result<Reparacion, ErrorIa> {
    let estado = app.state::<Estado>();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    estado.cancelar.store(false, Ordering::Relaxed);
    let config = estado.config();
    let perfil = estado.perfil(&config)?.clone();
    let modelos: Vec<String> = perfil.modelos().into_iter().map(String::from).collect();
    let (mut motor_reinstalado, mut capas_repuestas) = (false, 0);
    if estado.ollama_externo.is_none() {
        // Parar, reparar y volver a arrancar, sin que `asegurar_motor` arranque un motor en mitad de la reparación.
        let turno = estado.arranque.coger().await;
        // Parado, ningún archivo está en uso: en Windows no se podría reponer ni borrar.
        if let Some(mut p) = estado.sacar_motor(&turno) {
            p.parar();
        }
        let (ia, m, cancelar, lista) = (
            config.ia_efectiva(&estado.rutas),
            estado.catalogo.motor.clone(),
            estado.cancelar.clone(),
            modelos.clone(),
        );
        let canal_modelos = canal.clone();
        let comprobado = tauri::async_runtime::spawn_blocking(move || -> Result<(bool, usize), ErrorIa> {
            // `motor::Error::Red` (bajar el motor) llega con `red: true`; el resto, como texto.
            let reinstalado = motor::reparar(&ia, &m, &cancelar, &mut |p| {
                // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
                let _ = canal_motor.send(p);
            })?;
            let capas = modelos::reparar(&modelos::carpeta(&ia), &lista, &cancelar, &mut |hecho, total| {
                // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
                let _ = canal_modelos.send(ProgresoModelo {
                    modelo: String::new(),
                    estado: "verificando".into(),
                    hecho,
                    total,
                });
            })
            .map_err(|e| ErrorIa::from(e.to_string()))?;
            Ok((reinstalado, capas))
        })
        .await
        .map_err(|e| ErrorIa::from(e.to_string()))
        .and_then(|r| r);
        // Con lo que haya (el motor de antes si no se pudo reponer), el motor vuelve a arrancar.
        let arrancado = arrancar_con_turno(&app, &turno).await;
        if let Err(e) = &arrancado {
            // Sin motor no se queda callado: sale la pantalla «El motor se ha detenido».
            avisar_parada(&app, e.clone());
        }
        (motor_reinstalado, capas_repuestas) = comprobado?;
        arrancado?;
    }
    let cliente = estado.cliente()?;
    let cancelar = estado.cancelar.clone();
    let lista = modelos.clone();
    tauri::async_runtime::spawn_blocking(move || -> Result<(), ErrorIa> {
        for m in &lista {
            cliente.descargar_modelo(m, &cancelar, &mut |p| {
                // Si el frontal ya no escucha el canal (ventana cerrada), el progreso se pierde sin más: la tarea sigue.
                let _ = canal.send(p);
            })?;
        }
        Ok(())
    })
    .await
    .map_err(|e| ErrorIa::from(e.to_string()))??;
    Ok(Reparacion { motor_reinstalado, capas_repuestas, modelos })
}
