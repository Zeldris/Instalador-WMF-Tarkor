//! Estado compartido de la app (`Estado`), el candado de arranque, la marca de «ocupado» y los errores
//! que viajan al frontal.

use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError, Weak};
use std::time::Duration;
use tarkor_nucleo::catalogo::Perfil;
use tarkor_nucleo::catalogo::{Catalogo, Origen};
use tarkor_nucleo::config::{Config, Rutas};
use tarkor_nucleo::motor;
use tarkor_nucleo::ollama::{self, Cliente};
use tarkor_nucleo::procesos::{MotorDetenido, Proceso};

pub(crate) struct Estado {
    pub(crate) rutas: Rutas,
    pub(crate) catalogo: Catalogo,
    pub(crate) origen_catalogo: Origen,
    /// Ollama en marcha, o la URL de uno externo si se indicó `TARKOR_OLLAMA_URL`.
    pub(crate) motor: Mutex<Option<Proceso>>,
    /// URL del motor propio en marcha, aparte del `Mutex` del motor: la vigilancia lo tiene cogido
    /// hasta 30 s mientras lo relanza, y `cliente()` no puede esperar ahí. Secciones críticas cortas,
    /// nunca durante un arranque. Siempre pasa por `sacar_motor` y `poner_motor`.
    pub(crate) url_motor: Mutex<Option<String>>,
    pub(crate) ollama_externo: Option<String>,
    /// Las banderas de cancelar de las tareas en marcha: cada tarea coge la suya (`Cancelar::nueva`) y «Pausar»
    /// (`cancelar_descargas`) las levanta todas. Ninguna tarea baja la de otra.
    pub(crate) cancelar: Cancelar,
    /// La app se está cerrando: un arranque que acabe ahora para su motor en vez de dejarlo puesto (`RunEvent::Exit`).
    pub(crate) cerrando: AtomicBool,
    /// Lo que hizo una «Reparar» cortada por la red después de la comprobación local, para que el reintento no la
    /// repita ni pierda lo reparado.
    pub(crate) reparacion: Mutex<Option<ReparacionHecha>>,
    /// «Reparar», «Mover», cambiar de perfil o borrar modelos en marcha: tocan el motor o la carpeta
    /// de la IA, así que no pueden ir a la vez.
    pub(crate) ocupado: AtomicBool,
    /// Último aviso de motor detenido que el jugador aún no ha resuelto: el frontal lo lee al
    /// montarse (`motor_detenido`) por si el evento salió antes de que escuchara.
    pub(crate) detenido: Mutex<Option<MotorDetenido>>,
    /// Motivo de la última parada: se guarda al avisar y no se borra al arrancar (el aviso
    /// `detenido` sí); lo lee «Copiar informe».
    pub(crate) ultimo_motivo_parada: Mutex<Option<String>>,
    /// Pone en fila los arranques del motor (`arrancar_motor`, `asegurar_motor`): dos a la vez sacarían el motor recién
    /// puesto, su `Drop` lo mataría y lo que lo usara (calentar el narrador) fallaría. Quien para el motor para
    /// trabajar y volver a arrancarlo (Reparar, mover la carpeta, reintentar, cambiar de perfil) lo tiene cogido todo
    /// ese tramo, para que `asegurar_motor` no arranque un motor en mitad de la obra; y dentro arranca con
    /// `arrancar_con_turno`, nunca con `arrancar_motor` (que lo coge y se bloquearía).
    pub(crate) arranque: Candado,
}

pub(crate) mod arranque {
    use std::future::Future;
    use std::time::{Duration, Instant};
    use tauri::async_runtime::Mutex;

    /// El candado de `Estado::arranque`.
    #[derive(Default)]
    pub struct Candado(Mutex<()>);

    /// Un candado cogido. Solo lo da `Candado::coger`; `sacar_motor` y `poner_motor` (y con ellos `arrancar_con_turno`)
    /// lo piden y comprueban con `es_de` que sea el de `Estado::arranque`: cambiar el motor sin ese candado no compila,
    /// y con otro cae en el `assert`. La vigilancia (relanza el mismo proceso dentro de `Estado::motor`) y la salida
    /// (lo para al cerrar) también lo cogen, con `intentar` y `coger_antes_de`: no esperan a un arranque largo. La
    /// guarda va como `dyn` para no nombrar el tipo de tokio.
    pub struct Turno<'a> {
        candado: &'a Candado,
        _guarda: Box<dyn Send + Sync + 'a>,
    }

    impl Turno<'_> {
        pub fn es_de(&self, candado: &Candado) -> bool {
            std::ptr::eq(self.candado, candado)
        }
    }

    impl Candado {
        pub async fn coger(&self) -> Turno<'_> {
            Turno { candado: self, _guarda: Box::new(self.0.lock().await) }
        }

        /// El turno si está libre ahora, sin esperar (la vigilancia: si alguien arranca o para el motor, ese paso
        /// se lo salta).
        pub fn intentar(&self) -> Option<Turno<'_>> {
            let guarda = self.0.try_lock().ok()?;
            Some(Turno { candado: self, _guarda: Box::new(guarda) })
        }

        /// El turno, esperando como mucho `plazo` (síncrono: la salida de la app no corre en tokio).
        pub fn coger_antes_de(&self, plazo: Duration) -> Option<Turno<'_>> {
            let fin = Instant::now() + plazo;
            loop {
                if let Some(t) = self.intentar() {
                    return Some(t);
                }
                if Instant::now() >= fin {
                    return None;
                }
                std::thread::sleep(Duration::from_millis(20));
            }
        }

        /// El turno solo si hay que arrancar: con el candado cogido pregunta `en_marcha`, y si ya corre lo suelta. La
        /// comprobación y el arranque no se separan; quien recibe el turno lo tiene hasta acabar de arrancar.
        pub async fn turno_si_parado<F: Future<Output = bool>>(
            &self,
            en_marcha: impl FnOnce() -> F,
        ) -> Option<Turno<'_>> {
            let turno = self.coger().await;
            if en_marcha().await {
                None
            } else {
                Some(turno)
            }
        }
    }
}
pub(crate) use arranque::{Candado, Turno};

/// Las banderas de cancelar (`Estado::cancelar`). Antes era una sola que cada tarea ponía a `false` al empezar: una
/// tarea nueva deshacía la pausa de otra que aún no la había visto.
#[derive(Default)]
pub(crate) struct Cancelar(Mutex<Vec<Weak<AtomicBool>>>);

impl Cancelar {
    /// Una bandera para una tarea que empieza: sin cancelar, y sin tocar la de las demás.
    pub(crate) fn nueva(&self) -> Arc<AtomicBool> {
        let bandera = Arc::new(AtomicBool::new(false));
        let mut vivas = self.0.bloquear();
        vivas.retain(|b| b.strong_count() > 0);
        vivas.push(Arc::downgrade(&bandera));
        bandera
    }

    /// «Pausar»: cancela todas las tareas en marcha.
    pub(crate) fn todas(&self) {
        for b in self.0.bloquear().iter().filter_map(Weak::upgrade) {
            b.store(true, Ordering::SeqCst);
        }
    }
}

/// Lo hecho por una «Reparar» antes de que la red la cortara (`Estado::reparacion`).
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ReparacionHecha {
    pub(crate) ia: PathBuf,
    pub(crate) modelos: Vec<String>,
    pub(crate) motor_reinstalado: bool,
    pub(crate) capas_repuestas: usize,
}

impl ReparacionHecha {
    /// Lo hecho, si el reintento es de la misma carpeta y los mismos modelos; si no, se comprueba todo otra vez.
    pub(crate) fn para(guardada: Option<Self>, ia: &std::path::Path, modelos: &[String]) -> Option<Self> {
        guardada.filter(|h| h.ia == ia && h.modelos == modelos)
    }
}

/// Reintentos de `version()` antes de dar por caído un motor que tiene URL: un fallo suelto (el motor ocupado
/// cargando un modelo, un antivirus en Windows) no vale para reiniciar un motor sano.
pub(crate) const INTENTOS_VERSION: u32 = 3;
pub(crate) const ESPERA_VERSION: Duration = Duration::from_millis(300);

/// `prueba` hasta que conteste o se acaben los `intentos`, con `espera` entre uno y otro.
pub(crate) fn contesta_alguna_vez(intentos: u32, espera: Duration, mut prueba: impl FnMut() -> bool) -> bool {
    for i in 0..intentos {
        if prueba() {
            return true;
        }
        if i + 1 < intentos {
            std::thread::sleep(espera);
        }
    }
    false
}

/// Registro del motor de IA, dentro de `Rutas::registros`.
pub(crate) const REGISTRO_MOTOR: &str = "motor-ia.log";

/// Marca `Estado::ocupado` mientras vive; al soltarse (también por un error), la quita.
pub(crate) struct Ocupado<'a>(&'a AtomicBool);

impl<'a> Ocupado<'a> {
    /// Hay una tarea larga en marcha (sin cogerla).
    pub(crate) fn en_marcha(bandera: &AtomicBool) -> bool {
        bandera.load(Ordering::SeqCst)
    }

    pub(crate) fn tomar(bandera: &'a AtomicBool) -> Res<Self> {
        if bandera.swap(true, Ordering::SeqCst) {
            return Err(
                "Ya hay una reparación, un cambio de carpeta o de perfil en marcha; espera a que termine.".into()
            );
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
    pub(crate) fn config(&self) -> Config {
        Config::cargar(&self.rutas.datos)
    }

    /// Carpeta de la IA que se usa de verdad: la elegida por el jugador o la de por defecto.
    pub(crate) fn ia(&self) -> PathBuf {
        self.config().ia_efectiva(&self.rutas)
    }

    pub(crate) fn perfil(&self, config: &Config) -> Result<&Perfil, String> {
        let id = config.perfil.as_deref().ok_or("todavía no se ha elegido perfil")?;
        self.catalogo.perfil(id).ok_or_else(|| format!("perfil desconocido: {id}"))
    }

    /// Si el motor contesta ahora (bloqueante: red).
    pub(crate) fn en_marcha(&self) -> bool {
        self.cliente().and_then(|c| c.version().map_err(|e| e.to_string())).is_ok()
    }

    /// Como `en_marcha`, pero un fallo suelto no lo da por parado: lo usa `asegurar` antes de reiniciar el motor.
    /// Sin URL (motor sacado o nunca arrancado) contesta en seguida, sin reintentos.
    pub(crate) fn sigue_en_marcha(&self) -> bool {
        let Ok(cliente) = self.cliente() else { return false };
        contesta_alguna_vez(INTENTOS_VERSION, ESPERA_VERSION, || cliente.version().is_ok())
    }

    pub(crate) fn cliente(&self) -> Result<Cliente, String> {
        if let Some(url) = &self.ollama_externo {
            return Ok(Cliente::new(url.clone()));
        }
        let url = self.url_motor.bloquear().clone();
        url.map(Cliente::new).ok_or_else(|| "El motor de IA no está en marcha.".to_string())
    }

    /// Saca el motor propio del `Mutex` (y su URL) para pararlo o sustituirlo, con el candado de arranque cogido.
    pub(crate) fn sacar_motor(&self, turno: &Turno<'_>) -> Option<Proceso> {
        assert!(turno.es_de(&self.arranque), "sacar_motor con un turno que no es de Estado::arranque");
        let p = self.motor.bloquear().take();
        *self.url_motor.bloquear() = None;
        p
    }

    /// Pone el motor recién arrancado, con su URL.
    pub(crate) fn poner_motor(&self, proceso: Proceso, turno: &Turno<'_>) {
        assert!(turno.es_de(&self.arranque), "poner_motor con un turno que no es de Estado::arranque");
        let url = proceso.url();
        *self.motor.bloquear() = Some(proceso);
        *self.url_motor.bloquear() = Some(url);
    }
}

pub(crate) type Res<T> = Result<T, String>;

/// `lock()` que sigue dando el dato aunque otro hilo haya muerto con el mutex cogido (envenenado). Los datos de
/// `Estado` son valores sueltos (URL, aviso, proceso) que no quedan a medias, y un `unwrap` aquí tiraría la
/// vigilancia o el cierre de la app por un pánico ajeno.
pub(crate) trait Bloquear<T> {
    fn bloquear(&self) -> MutexGuard<'_, T>;
}

impl<T> Bloquear<T> for Mutex<T> {
    fn bloquear(&self) -> MutexGuard<'_, T> {
        self.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Error de una descarga que el frontal distingue por su clase (`INS-42`): `red` (se perdió internet: la Descarga
/// espera y reintenta sola) y `sin_memoria` (pide un perfil más ligero). Viaja como objeto, no como texto.
#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ErrorIa {
    mensaje: String,
    pub(crate) red: bool,
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

/// Una tarea en segundo plano que no terminó (`spawn_blocking`).
impl From<tauri::Error> for ErrorIa {
    fn from(e: tauri::Error) -> Self {
        ErrorIa::from(e.to_string())
    }
}

impl From<tarkor_nucleo::modelos::Error> for ErrorIa {
    fn from(e: tarkor_nucleo::modelos::Error) -> Self {
        ErrorIa::from(e.to_string())
    }
}

/// Para que `?` siga sirviendo dentro de los comandos que devuelven `Res`.
impl From<ErrorIa> for String {
    fn from(e: ErrorIa) -> Self {
        e.mensaje
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::future::Future;
    use std::path::Path;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    #[test]
    fn bloquear_da_el_dato_con_el_mutex_envenenado() {
        let m = Arc::new(Mutex::new(Some(7)));
        let m2 = m.clone();
        let _ = std::thread::spawn(move || {
            let _guarda = m2.lock().unwrap();
            panic!("envenena el mutex");
        })
        .join();
        assert!(m.is_poisoned(), "el mutex debe estar envenenado");
        assert_eq!(*m.bloquear(), Some(7));
        *m.bloquear() = None;
        assert_eq!(*m.bloquear(), None);
    }

    #[test]
    fn turno_si_parado_solo_cuando_no_corre() {
        let candado = Candado::default();
        assert!(tauri::async_runtime::block_on(candado.turno_si_parado(|| async { false })).is_some(), "parado: turno");
        assert!(tauri::async_runtime::block_on(candado.turno_si_parado(|| async { true })).is_none(), "en marcha: no");
    }

    #[test]
    fn el_turno_sabe_de_que_candado_es() {
        let (uno, otro) = (Candado::default(), Candado::default());
        let turno = tauri::async_runtime::block_on(uno.coger());
        assert!(turno.es_de(&uno));
        assert!(!turno.es_de(&otro), "el turno de otro candado no vale para Estado::arranque");
    }

    #[test]
    fn dos_asegurar_a_la_vez_arrancan_una_sola_vez() {
        let candado = Candado::default();
        let en_marcha = AtomicBool::new(false);
        let arranques = AtomicUsize::new(0);
        let uno = || async {
            // Como `asegurar`: el turno se tiene hasta acabar de arrancar.
            if let Some(_turno) = candado.turno_si_parado(|| async { en_marcha.load(Ordering::SeqCst) }).await {
                arranques.fetch_add(1, Ordering::SeqCst);
                // El arranque tarda: el segundo espera el candado y, al entrar, ya lo ve en marcha.
                tauri::async_runtime::spawn_blocking(|| std::thread::sleep(std::time::Duration::from_millis(100)))
                    .await
                    .unwrap();
                en_marcha.store(true, Ordering::SeqCst);
            }
        };
        tauri::async_runtime::block_on(unir(uno(), uno()));
        assert_eq!(arranques.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn una_tarea_nueva_no_deshace_la_pausa_de_otra() {
        let cancelar = Cancelar::default();
        let descarga = cancelar.nueva();
        cancelar.todas();
        let cambio_de_perfil = cancelar.nueva();
        assert!(descarga.load(Ordering::SeqCst), "la pausa de la descarga sigue en pie");
        assert!(!cambio_de_perfil.load(Ordering::SeqCst), "la tarea nueva empieza sin cancelar");
        cancelar.todas();
        assert!(cambio_de_perfil.load(Ordering::SeqCst), "«Pausar» llega también a la nueva");
    }

    #[test]
    fn un_fallo_suelto_de_version_no_da_el_motor_por_caido() {
        let mut veces = 0;
        assert!(contesta_alguna_vez(3, Duration::ZERO, || {
            veces += 1;
            veces >= 2
        }));
        let mut veces = 0;
        assert!(!contesta_alguna_vez(3, Duration::ZERO, || {
            veces += 1;
            false
        }));
        assert_eq!(veces, 3, "caído de verdad: se prueba un número limitado de veces");
    }

    #[test]
    fn el_reintento_de_reparar_recupera_lo_hecho() {
        let hecha = ReparacionHecha {
            ia: PathBuf::from("/ia"),
            modelos: vec!["a".into()],
            motor_reinstalado: true,
            capas_repuestas: 2,
        };
        assert_eq!(ReparacionHecha::para(Some(hecha.clone()), Path::new("/ia"), &["a".into()]), Some(hecha.clone()));
        assert_eq!(ReparacionHecha::para(Some(hecha.clone()), Path::new("/otra"), &["a".into()]), None);
        assert_eq!(ReparacionHecha::para(Some(hecha), Path::new("/ia"), &["b".into()]), None, "otro perfil");
    }

    #[test]
    fn la_vigilancia_no_entra_mientras_alguien_tiene_el_turno() {
        let candado = Candado::default();
        let arrancando = tauri::async_runtime::block_on(candado.coger());
        assert!(candado.intentar().is_none(), "con un arranque en marcha, la vigilancia se salta el paso");
        let inicio = std::time::Instant::now();
        assert!(candado.coger_antes_de(Duration::from_millis(100)).is_none());
        assert!(inicio.elapsed() < Duration::from_secs(2), "la salida no espera más del plazo");
        drop(arrancando);
        assert!(candado.intentar().is_some());
        assert!(candado.coger_antes_de(Duration::ZERO).is_some());
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
            if ra.is_some() && rb.is_some() {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        })
        .await;
        (ra.unwrap(), rb.unwrap())
    }
}
