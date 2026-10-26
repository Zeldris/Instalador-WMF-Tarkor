//! App de escritorio de Tarkor: expone al asistente el análisis del equipo, el catálogo, la
//! configuración y el motor de IA (instalación, arranque, modelos y comprobaciones). El backend
//! del juego se añadirá como segundo proceso en la fase 4 con el mismo gestor (`procesos`).

use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tarkor_nucleo::carpetas::{espacio_libre_mb, mover_carpeta};
use tarkor_nucleo::catalogo::{Catalogo, Origen, Perfil};
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::equipo::{self, Equipo};
use tarkor_nucleo::informe::{self, EstadoMotor};
use tarkor_nucleo::ollama::{self, resumen_uso, tiene, Cargado, Cliente, ProgresoModelo, Uso};
use tarkor_nucleo::perfiles::{self, Evaluacion, UsoCpu};
use tarkor_nucleo::procesos::{self, Especificacion, MotorDetenido, Proceso};
use tarkor_nucleo::rendimiento::{self, Ajustes};
use tarkor_nucleo::{modelos, motor, rendimiento::hilos_para_ia};
use tauri::async_runtime::Mutex as MutexAsincrono;
use tauri::ipc::Channel;
use tauri::{Emitter, Manager, RunEvent, State};

struct Estado {
    rutas: Rutas,
    catalogo: Catalogo,
    origen_catalogo: Origen,
    /// Ollama en marcha, o la URL de uno externo si se indicó `TARKOR_OLLAMA_URL`.
    motor: Mutex<Option<Proceso>>,
    /// URL del motor propio en marcha, aparte del `Mutex` del motor: la vigilancia lo tiene cogido
    /// hasta 30 s mientras lo relanza, y `cliente()` no puede esperar ahí. Secciones críticas cortas,
    /// nunca durante un arranque. Siempre pasa por `sacar_motor` y `poner_motor`.
    url_motor: Mutex<Option<String>>,
    ollama_externo: Option<String>,
    cancelar: Arc<AtomicBool>,
    /// «Reparar», «Mover», cambiar de perfil o borrar modelos en marcha: tocan el motor o la carpeta
    /// de la IA, así que no pueden ir a la vez.
    ocupado: AtomicBool,
    /// Último aviso de motor detenido que el jugador aún no ha resuelto: el frontal lo lee al
    /// montarse (`motor_detenido`) por si el evento salió antes de que escuchara.
    detenido: Mutex<Option<MotorDetenido>>,
    /// Motivo de la última parada: se guarda al avisar y no se borra al arrancar (el aviso
    /// `detenido` sí); lo lee «Copiar informe».
    ultimo_motivo_parada: Mutex<Option<String>>,
    /// Pone en fila los arranques del motor (`arrancar_motor`, `asegurar_motor`): dos a la vez sacarían el motor recién
    /// puesto, su `Drop` lo mataría y lo que lo usara (calentar el narrador) fallaría. Quien para el motor para
    /// trabajar y volver a arrancarlo (Reparar, mover la carpeta, reintentar, cambiar de perfil) lo tiene cogido todo
    /// ese tramo, para que `asegurar_motor` no arranque un motor en mitad de la obra; y dentro arranca con
    /// `arrancar_sin_candado`, nunca con `arrancar_motor` (que lo coge y se bloquearía).
    arranque: MutexAsincrono<()>,
}

/// Registro del motor de IA, dentro de `Rutas::registros`.
const REGISTRO_MOTOR: &str = "motor-ia.log";

/// Marca `Estado::ocupado` mientras vive; al soltarse (también por un error), la quita.
struct Ocupado<'a>(&'a AtomicBool);

impl<'a> Ocupado<'a> {
    fn tomar(bandera: &'a AtomicBool) -> Res<Self> {
        if bandera.swap(true, Ordering::SeqCst) {
            return Err("Ya hay una reparación, un cambio de carpeta o de perfil en marcha; espera a que termine.".into());
        }
        Ok(Ocupado(bandera))
    }
}

impl Drop for Ocupado<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

impl Estado {
    fn config(&self) -> Config {
        Config::cargar(&self.rutas.datos)
    }

    /// Carpeta de la IA que se usa de verdad: la elegida por el jugador o la de por defecto.
    fn ia(&self) -> PathBuf {
        self.config().ia_efectiva(&self.rutas)
    }

    fn perfil(&self, config: &Config) -> Result<&Perfil, String> {
        let id = config.perfil.as_deref().ok_or("todavía no se ha elegido perfil")?;
        self.catalogo.perfil(id).ok_or_else(|| format!("perfil desconocido: {id}"))
    }

    /// Si el motor contesta ahora (bloqueante: red).
    fn en_marcha(&self) -> bool {
        self.cliente().and_then(|c| c.version().map_err(|e| e.to_string())).is_ok()
    }

    fn cliente(&self) -> Result<Cliente, String> {
        if let Some(url) = &self.ollama_externo {
            return Ok(Cliente::new(url.clone()));
        }
        let url = self.url_motor.lock().unwrap().clone();
        url.map(Cliente::new).ok_or_else(|| "El motor de IA no está en marcha.".to_string())
    }

    /// Saca el motor propio del `Mutex` (y su URL) para pararlo o sustituirlo.
    fn sacar_motor(&self) -> Option<Proceso> {
        let p = self.motor.lock().unwrap().take();
        *self.url_motor.lock().unwrap() = None;
        p
    }

    /// Pone el motor recién arrancado, con su URL.
    fn poner_motor(&self, proceso: Proceso) {
        let url = proceso.url();
        *self.motor.lock().unwrap() = Some(proceso);
        *self.url_motor.lock().unwrap() = Some(url);
    }
}

type Res<T> = Result<T, String>;

/// Error de una descarga que el frontal distingue por su clase (`INS-42`): `red` (se perdió internet: la Descarga
/// espera y reintenta sola) y `sin_memoria` (pide un perfil más ligero). Viaja como objeto, no como texto.
#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ErrorIa {
    mensaje: String,
    red: bool,
    sin_memoria: bool,
}

impl From<String> for ErrorIa {
    fn from(mensaje: String) -> Self {
        ErrorIa { mensaje, red: false, sin_memoria: false }
    }
}

impl From<ollama::Error> for ErrorIa {
    fn from(e: ollama::Error) -> Self {
        ErrorIa { mensaje: e.to_string(), red: e.es_de_red(), sin_memoria: e.sin_memoria() }
    }
}

impl From<motor::Error> for ErrorIa {
    fn from(e: motor::Error) -> Self {
        ErrorIa { mensaje: e.to_string(), red: e.es_de_red(), sin_memoria: false }
    }
}

/// Para que `?` siga sirviendo dentro de los comandos que devuelven `Res`.
impl From<ErrorIa> for String {
    fn from(e: ErrorIa) -> Self {
        e.mensaje
    }
}

#[tauri::command]
fn rutas(estado: State<'_, Estado>) -> Rutas {
    Rutas { ia: estado.ia(), ..estado.rutas.clone() }
}

/// De dónde salió el catálogo (incrustado, externo, o externo inválido y por qué).
#[tauri::command]
fn origen_catalogo(estado: State<'_, Estado>) -> Origen {
    estado.origen_catalogo.clone()
}

#[tauri::command]
fn cargar_config(estado: State<'_, Estado>) -> Config {
    estado.config()
}

#[tauri::command]
fn guardar_config(estado: State<'_, Estado>, config: Config) -> Res<()> {
    config.guardar(&estado.rutas.datos).map_err(|e| e.to_string())
}

/// Solo se llama tras el permiso explícito del jugador (pantalla 3 del asistente).
#[tauri::command]
async fn analizar_equipo(estado: State<'_, Estado>) -> Res<Equipo> {
    let datos = estado.rutas.datos.clone();
    tauri::async_runtime::spawn_blocking(move || equipo::analizar(&datos)).await.map_err(|e| e.to_string())
}

#[tauri::command]
fn evaluar_perfiles(estado: State<'_, Estado>, equipo: Option<Equipo>) -> Evaluacion {
    perfiles::evaluar(&estado.catalogo, equipo.as_ref(), espacio_libre_mb(&estado.ia()))
}

#[tauri::command]
fn ajustes_rendimiento(estado: State<'_, Estado>, perfil: String, equipo: Option<Equipo>, uso_cpu: UsoCpu) -> Res<Ajustes> {
    let p = estado.catalogo.perfil(&perfil).ok_or_else(|| format!("perfil desconocido: {perfil}"))?;
    Ok(rendimiento::calcular(&estado.catalogo, p, equipo.as_ref(), uso_cpu))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct InfoMotor {
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
async fn estado_motor(app: tauri::AppHandle) -> Res<InfoMotor> {
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
fn cancelar_descargas(estado: State<'_, Estado>) {
    estado.cancelar.store(true, Ordering::Relaxed);
}

#[tauri::command]
async fn instalar_motor(app: tauri::AppHandle, canal: Channel<motor::Progreso>) -> Result<(), ErrorIa> {
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
async fn iniciar_motor(app: tauri::AppHandle) -> Res<()> {
    arrancar_motor(&app).await
}

/// Arranca solo si el motor no está en marcha, sin reiniciar uno que ya corre (`iniciar_motor` sí lo haría). Lo usa el
/// juego al entrar (`INS-42`). Comprobar y arrancar van bajo el mismo candado que `arrancar_motor`: dos entradas
/// seguidas, o un cambio de perfil a la vez, no lanzan dos arranques. Con un Ollama externo no hace nada.
#[tauri::command]
async fn asegurar_motor(app: tauri::AppHandle) -> Res<()> {
    asegurar(&app).await
}

/// Lo que hace `asegurar_motor`; también lo usa `cambiar_perfil` para tener motor antes de descargar.
async fn asegurar(app: &tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    asegurar_con(
        &estado.arranque,
        || async {
            let a = app.clone();
            tauri::async_runtime::spawn_blocking(move || a.state::<Estado>().en_marcha()).await.unwrap_or(false)
        },
        || arrancar_sin_candado(app),
    )
    .await
}

/// Toma el candado y arranca solo si `en_marcha` dice que no corre: la comprobación y el arranque no se separan.
async fn asegurar_con<E, F, A, G>(candado: &MutexAsincrono<()>, en_marcha: E, arrancar: A) -> Res<()>
where
    E: FnOnce() -> F,
    F: Future<Output = bool>,
    A: FnOnce() -> G,
    G: Future<Output = Res<()>>,
{
    let _fila = candado.lock().await;
    if en_marcha().await {
        return Ok(());
    }
    arrancar().await
}

/// Lo que hace `iniciar_motor`. En fila con cualquier otro arranque: quien ya tenga `Estado::arranque` cogido usa
/// `arrancar_sin_candado`.
async fn arrancar_motor(app: &tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    let _fila = estado.arranque.lock().await;
    arrancar_sin_candado(app).await
}

/// El arranque en sí: quien lo llama ya tiene `Estado::arranque`.
async fn arrancar_sin_candado(app: &tauri::AppHandle) -> Res<()> {
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
    if let Some(mut viejo) = estado.sacar_motor() {
        viejo.parar();
    }
    let proceso = tauri::async_runtime::spawn_blocking(move || Proceso::arrancar(espec))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?;
    estado.poner_motor(proceso);
    // Un motor nuevo y sano: el aviso de la parada anterior ya no vale.
    *estado.detenido.lock().unwrap() = None;
    Ok(())
}

/// Vuelve a arrancar el motor tras un error; si no arranca, avisa de la parada. Quien llama ya tiene
/// `Estado::arranque`.
async fn rearrancar_o_avisar(app: &tauri::AppHandle) {
    if let Err(e) = arrancar_sin_candado(app).await {
        avisar_parada(app, e);
    }
}

/// Mueve la carpeta de la IA a `<destino>/Tarkor IA` (como la «SteamLibrary» que crea Steam
/// dentro de la carpeta elegida), guarda la nueva ruta en `config.json` y devuelve las rutas
/// efectivas. Para el motor mientras se mueve y, si estaba en marcha, lo arranca con la ruta
/// nueva; si el movimiento falla, lo deja como estaba. Si ya es esa carpeta, no hace nada; si se
/// elige una «Tarkor IA», se usa tal cual en vez de anidar otra.
///
/// Un error después de mover (el motor no arranca) llega con la carpeta ya cambiada y guardada:
/// el asistente vuelve a leer `config.json` y las rutas en cualquier error.
#[tauri::command]
async fn cambiar_carpeta_ia(app: tauri::AppHandle, destino: String) -> Res<Rutas> {
    let estado = app.state::<Estado>();
    let elegida = PathBuf::from(destino);
    let nueva = if elegida.file_name().is_some_and(|n| n == "Tarkor IA") { elegida } else { elegida.join("Tarkor IA") };
    let actual = estado.ia();
    if nueva == actual {
        return Ok(Rutas { ia: actual, ..estado.rutas.clone() });
    }
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    // Parar, mover y volver a arrancar, sin que `asegurar_motor` arranque un motor en mitad del movimiento.
    let _fila = estado.arranque.lock().await;
    let parado = estado.sacar_motor();
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
            rearrancar_o_avisar(&app).await;
        }
        return Err(e);
    }
    // Se vuelve a leer: lo que el asistente guardara durante la copia no se pisa.
    let mut config = estado.config();
    config.carpeta_ia = Some(nueva.clone());
    if let Err(e) = config.guardar(&estado.rutas.datos) {
        // Sin guardar, la próxima apertura buscaría la IA en la carpeta de antes: se devuelve allí.
        let (a, b) = (nueva.clone(), actual.clone());
        let vuelta = tauri::async_runtime::spawn_blocking(move || mover_carpeta(&a, &b)).await.map_err(|e| e.to_string()).and_then(|r| r);
        if en_marcha {
            rearrancar_o_avisar(&app).await;
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
        if let Err(e) = arrancar_sin_candado(&app).await {
            avisar_parada(&app, e.clone());
            return Err(format!("La carpeta se movió a {}, pero el motor de IA no arranca: {e}", nueva.display()));
        }
    }
    Ok(Rutas { ia: nueva, ..estado.rutas.clone() })
}

/// Baja los `modelos` que `cliente` aún no tiene, avisando por `canal`. Ollama reanuda lo que se
/// quedara a medias; `cancelar` corta la descarga en curso.
fn descargar_faltantes(cliente: &Cliente, modelos: &[String], cancelar: &AtomicBool, canal: &Channel<ProgresoModelo>) -> Result<(), ollama::Error> {
    let hay = cliente.modelos()?;
    for m in modelos {
        if tiene(&hay, m) {
            let _ = canal.send(ProgresoModelo { modelo: m.clone(), estado: "success".into(), hecho: 1, total: 1 });
            continue;
        }
        cliente.descargar_modelo(m, cancelar, &mut |p| {
            let _ = canal.send(p);
        })?;
    }
    Ok(())
}

/// Descarga los modelos del perfil que falten. Ollama reanuda lo que se quedara a medias.
#[tauri::command]
async fn descargar_modelos(app: tauri::AppHandle, canal: Channel<ProgresoModelo>) -> Result<Vec<String>, ErrorIa> {
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
async fn calentar_narrador(app: tauri::AppHandle) -> Result<(), ErrorIa> {
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
async fn cambiar_perfil(app: tauri::AppHandle, perfil: String, canal: Channel<ProgresoModelo>) -> Result<Config, ErrorIa> {
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
    let _fila = estado.arranque.lock().await;
    config.guardar(&estado.rutas.datos).map_err(|e| ErrorIa::from(format!("No se pudo guardar el perfil nuevo ({e}); sigue el de antes.")))?;
    if estado.ollama_externo.is_none() {
        if let Err(e) = arrancar_sin_candado(&app).await {
            // Sin motor con el perfil nuevo no se queda a medias: vuelve el de antes, con su motor.
            let mut vuelta = estado.config();
            vuelta.perfil = antes.perfil.clone();
            vuelta.modelos_descargados = antes.modelos_descargados.clone();
            let guardado = vuelta.guardar(&estado.rutas.datos);
            let vuelto = arrancar_sin_candado(&app).await;
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
struct Sobrante {
    modelo: String,
    gb: f64,
}

/// Los modelos del Ollama propio que no son del perfil actual. Con un Ollama externo, ninguno: los
/// modelos del jugador no se tocan.
fn sobrantes_de(estado: &Estado) -> Res<Vec<(String, u64)>> {
    if estado.ollama_externo.is_some() {
        return Ok(Vec::new());
    }
    let perfil = estado.perfil(&estado.config())?.clone();
    let hay = estado.cliente()?.modelos_con_tamano().map_err(|e| e.to_string())?;
    Ok(ollama::sobrantes(hay, &perfil.modelos()))
}

#[tauri::command]
async fn modelos_sobrantes(app: tauri::AppHandle) -> Res<Vec<Sobrante>> {
    let lista = tauri::async_runtime::spawn_blocking(move || sobrantes_de(&app.state::<Estado>())).await.map_err(|e| e.to_string())??;
    Ok(lista.into_iter().map(|(modelo, bytes)| Sobrante { modelo, gb: (bytes as f64 / 1e9 * 100.0).round() / 100.0 }).collect())
}

/// Borra modelos sobrantes. Solo borra los que siguen siéndolo al llamar (se recalcula): nunca uno
/// del perfil, aunque el frontal tenga una lista vieja. Rechaza un Ollama externo.
#[tauri::command]
async fn borrar_modelos(app: tauri::AppHandle, modelos: Vec<String>) -> Res<()> {
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

/// Dónde corre la IA ahora mismo (`/api/ps`). Error si el motor no está en marcha.
#[tauri::command]
async fn uso_ia(app: tauri::AppHandle) -> Res<Uso> {
    let cliente = app.state::<Estado>().cliente()?;
    let cargados = tauri::async_runtime::spawn_blocking(move || cliente.cargados()).await.map_err(|e| e.to_string())?.map_err(|e| e.to_string())?;
    Ok(resumen_uso(&cargados))
}

/// El texto de «Copiar informe» (docs/11), con la carpeta personal cambiada por `~`.
#[tauri::command]
async fn informe(app: tauri::AppHandle) -> Res<String> {
    tauri::async_runtime::spawn_blocking(move || {
        let estado = app.state::<Estado>();
        let config = estado.config();
        let perfil = config.perfil.as_deref().and_then(|id| estado.catalogo.perfil(id));
        let ajustes = perfil.map(|p| rendimiento::calcular(&estado.catalogo, p, config.equipo.as_ref(), config.uso_cpu));
        let cliente = estado.cliente();
        let version = cliente.as_ref().ok().and_then(|c| c.version().ok());
        let ps: Res<Vec<Cargado>> = cliente.and_then(|c| c.cargados().map_err(|e| e.to_string()));
        let registro = informe::ultimas_lineas(&estado.rutas.registros.join(REGISTRO_MOTOR), informe::LINEAS_REGISTRO);
        let ultimo = estado.ultimo_motivo_parada.lock().unwrap().clone();
        let motor = EstadoMotor {
            version_catalogo: &estado.catalogo.motor.version,
            version_en_marcha: version.as_deref(),
            instalado: estado.ollama_externo.is_some() || motor::instalado(&config.ia_efectiva(&estado.rutas), &estado.catalogo.motor),
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

/// Guarda el aviso de motor detenido y lo emite como evento `motor-detenido`.
fn avisar_parada(app: &tauri::AppHandle, motivo: String) {
    let estado = app.state::<Estado>();
    let cola = informe::ultimas_lineas(&estado.rutas.registros.join(REGISTRO_MOTOR), informe::LINEAS_REGISTRO);
    // Solo el último arranque: una falta de memoria de uno anterior no cuenta.
    let aviso = MotorDetenido { motivo: motivo.clone(), sin_memoria: procesos::sin_memoria(procesos::desde_ultimo_arranque(&cola)) };
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
fn vigilar_una_vez(app: &tauri::AppHandle) {
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
fn motor_detenido(estado: State<'_, Estado>) -> Option<MotorDetenido> {
    estado.detenido.lock().unwrap().clone()
}

/// «Reintentar» de la pantalla «El motor se ha detenido»: saca el motor viejo del `Mutex`, borra el
/// aviso y vuelve a arrancar con `arrancar_sin_candado` (puerto nuevo y config al día, hasta 30 s). Si
/// falla, se vuelve a guardar y emitir el aviso.
#[tauri::command]
async fn reintentar_motor(app: tauri::AppHandle) -> Res<()> {
    let estado = app.state::<Estado>();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    let _fila = estado.arranque.lock().await;
    // Primero se saca el proceso y luego se borra el aviso: la vigilancia no ve un motor caído sin
    // aviso y lo avisa otra vez mientras se reintenta.
    let viejo = estado.sacar_motor();
    *estado.detenido.lock().unwrap() = None;
    if let Some(mut v) = viejo {
        v.parar();
    }
    match arrancar_sin_candado(&app).await {
        Ok(()) => Ok(()),
        Err(motivo) => {
            avisar_parada(&app, motivo.clone());
            Err(motivo)
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Reparacion {
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
async fn reparar(app: tauri::AppHandle, canal_motor: Channel<motor::Progreso>, canal: Channel<ProgresoModelo>) -> Result<Reparacion, ErrorIa> {
    let estado = app.state::<Estado>();
    let _ocupado = Ocupado::tomar(&estado.ocupado)?;
    estado.cancelar.store(false, Ordering::Relaxed);
    let config = estado.config();
    let perfil = estado.perfil(&config)?.clone();
    let modelos: Vec<String> = perfil.modelos().into_iter().map(String::from).collect();
    let (mut motor_reinstalado, mut capas_repuestas) = (false, 0);
    if estado.ollama_externo.is_none() {
        // Parar, reparar y volver a arrancar, sin que `asegurar_motor` arranque un motor en mitad de la reparación.
        let _fila = estado.arranque.lock().await;
        // Parado, ningún archivo está en uso: en Windows no se podría reponer ni borrar.
        if let Some(mut p) = estado.sacar_motor() {
            p.parar();
        }
        let (ia, m, cancelar, lista) = (config.ia_efectiva(&estado.rutas), estado.catalogo.motor.clone(), estado.cancelar.clone(), modelos.clone());
        let canal_modelos = canal.clone();
        let comprobado = tauri::async_runtime::spawn_blocking(move || -> Result<(bool, usize), ErrorIa> {
            // `motor::Error::Red` (bajar el motor) llega con `red: true`; el resto, como texto.
            let reinstalado = motor::reparar(&ia, &m, &cancelar, &mut |p| {
                let _ = canal_motor.send(p);
            })?;
            let capas = modelos::reparar(&modelos::carpeta(&ia), &lista, &cancelar, &mut |hecho, total| {
                let _ = canal_modelos.send(ProgresoModelo { modelo: String::new(), estado: "verificando".into(), hecho, total });
            })
            .map_err(|e| ErrorIa::from(e.to_string()))?;
            Ok((reinstalado, capas))
        })
        .await
        .map_err(|e| ErrorIa::from(e.to_string()))
        .and_then(|r| r);
        // Con lo que haya (el motor de antes si no se pudo reponer), el motor vuelve a arrancar.
        let arrancado = arrancar_sin_candado(&app).await;
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
                let _ = canal.send(p);
            })?;
        }
        Ok(())
    })
    .await
    .map_err(|e| ErrorIa::from(e.to_string()))??;
    Ok(Reparacion { motor_reinstalado, capas_repuestas, modelos })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase", tag = "resultado")]
enum Comprobacion {
    Ok { detalle: String },
    /// Todavía no aplica en esta fase (llega con el juego empaquetado, fase 4).
    Omitida { motivo: String },
}

/// Una de las comprobaciones de docs/07, por id.
#[tauri::command]
async fn comprobar(app: tauri::AppHandle, id: String) -> Res<Comprobacion> {
    let estado = app.state::<Estado>();
    let pendiente = || Ok(Comprobacion::Omitida { motivo: "Llega con el juego empaquetado (fase 4).".into() });
    match id.as_str() {
        "datos" => {
            let prueba = estado.rutas.datos.join(".prueba-escritura");
            fs::create_dir_all(&estado.rutas.datos)
                .and_then(|_| fs::write(&prueba, b"ok"))
                .and_then(|_| fs::remove_file(&prueba))
                .map_err(|e| format!("No se puede escribir en la carpeta de datos ({}): {e}", estado.rutas.datos.display()))?;
            Ok(Comprobacion::Ok { detalle: format!("Se puede escribir en {}.", estado.rutas.datos.display()) })
        }
        "basedatos" | "juego" | "mundo" => pendiente(),
        "motor" => {
            let cliente = estado.cliente()?;
            let v = tauri::async_runtime::spawn_blocking(move || cliente.version()).await.map_err(|e| e.to_string())?.map_err(|e| e.to_string())?;
            Ok(Comprobacion::Ok { detalle: format!("En marcha (Ollama {v}).") })
        }
        "modelos" => {
            let perfil = estado.perfil(&estado.config())?.clone();
            let cliente = estado.cliente()?;
            let hay = tauri::async_runtime::spawn_blocking(move || cliente.modelos()).await.map_err(|e| e.to_string())?.map_err(|e| e.to_string())?;
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
                detalle: serde_json::json!({ "texto": prueba.texto, "tokensPorSegundo": prueba.tokens_por_segundo }).to_string(),
            })
        }
        otro => Err(format!("comprobación desconocida: {otro}")),
    }
}

pub fn run() {
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
            cancelar: Arc::new(AtomicBool::new(false)),
            ocupado: AtomicBool::new(false),
            detenido: Mutex::new(None),
            ultimo_motivo_parada: Mutex::new(None),
            arranque: MutexAsincrono::new(()),
        })
        .invoke_handler(tauri::generate_handler![
            rutas,
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
            if let Some(mut p) = app.state::<Estado>().motor.lock().unwrap().take() {
                p.parar();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    #[test]
    fn asegurar_arranca_si_no_corre_y_no_reinicia_si_corre() {
        let candado = MutexAsincrono::new(());
        let arranques = AtomicUsize::new(0);
        let arrancar = || async {
            arranques.fetch_add(1, Ordering::SeqCst);
            Ok(())
        };
        tauri::async_runtime::block_on(asegurar_con(&candado, || async { false }, arrancar)).unwrap();
        assert_eq!(arranques.load(Ordering::SeqCst), 1, "parado: arranca");
        tauri::async_runtime::block_on(asegurar_con(&candado, || async { true }, arrancar)).unwrap();
        assert_eq!(arranques.load(Ordering::SeqCst), 1, "en marcha: no lo reinicia");
    }

    #[test]
    fn dos_asegurar_a_la_vez_arrancan_una_sola_vez() {
        let candado = MutexAsincrono::new(());
        let en_marcha = AtomicBool::new(false);
        let arranques = AtomicUsize::new(0);
        let uno = || {
            asegurar_con(
                &candado,
                || async { en_marcha.load(Ordering::SeqCst) },
                || async {
                    arranques.fetch_add(1, Ordering::SeqCst);
                    // El arranque tarda: el segundo espera el candado y, al entrar, ya lo ve en marcha.
                    tauri::async_runtime::spawn_blocking(|| std::thread::sleep(std::time::Duration::from_millis(100)))
                        .await
                        .unwrap();
                    en_marcha.store(true, Ordering::SeqCst);
                    Ok(())
                },
            )
        };
        let (a, b) = tauri::async_runtime::block_on(unir(uno(), uno()));
        a.unwrap();
        b.unwrap();
        assert_eq!(arranques.load(Ordering::SeqCst), 1);
    }

    /// `join` de dos futuros sin añadir `futures` al crate.
    async fn unir<A: Future, B: Future>(a: A, b: B) -> (A::Output, B::Output) {
        use std::pin::pin;
        use std::task::Poll;
        let (mut a, mut b) = (pin!(a), pin!(b));
        let (mut ra, mut rb) = (None, None);
        std::future::poll_fn(|cx| {
            if ra.is_none() {
                if let Poll::Ready(v) = a.as_mut().poll(cx) {
                    ra = Some(v);
                }
            }
            if rb.is_none() {
                if let Poll::Ready(v) = b.as_mut().poll(cx) {
                    rb = Some(v);
                }
            }
            if ra.is_some() && rb.is_some() { Poll::Ready(()) } else { Poll::Pending }
        })
        .await;
        (ra.unwrap(), rb.unwrap())
    }
}
