//! Instalación del motor de IA (Ollama) en la carpeta de la app, sin permisos de administrador
//! ni tocar el sistema (docs/03, "Decisión"; fase 0.5 de docs/05).
//!
//! 1. Descarga el paquete oficial de la versión fijada en el catálogo. Si se corta, se reanuda
//!    donde se quedó (`.part` + cabecera Range).
//! 2. Comprueba su SHA256 contra la suma del catálogo. Si no coincide, lo borra y avisa.
//! 3. Lo extrae en una carpeta temporal y la renombra al final: nunca queda un motor a medias.
//! 4. Borra el paquete descargado para no ocupar el doble. Antes apunta en `.completo` la suma de
//!    cada archivo extraído, para que «Reparar» ([`reparar`]) pueda comprobarlo sin el paquete.

use crate::catalogo::{Motor, PaqueteMotor};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

const MARCA_COMPLETO: &str = ".completo";

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase", tag = "fase")]
pub enum Progreso {
    Descargando { hecho: u64, total: u64 },
    Verificando,
    Extrayendo,
    Listo,
}

#[derive(Debug)]
pub enum Error {
    SinPaquete,
    Cancelado,
    /// La suma no coincide: la descarga llegó dañada o no es el fichero esperado.
    Danado,
    /// Fallo de transporte (sin conexión, DNS, tiempo agotado, corte a media descarga): vuelve a intentarse solo.
    Red(String),
    /// El servidor respondió con un código HTTP de error (404, 403...) o falló el certificado TLS: hay conexión,
    /// así que esperar a que vuelva internet no lo arregla.
    Servidor(String),
    Disco(io::Error),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::SinPaquete => write!(f, "No hay motor de IA para este sistema operativo."),
            Error::Cancelado => write!(f, "Descarga cancelada. Lo descargado se conserva para continuar."),
            Error::Danado => write!(f, "El motor de IA se descargó dañado. Se ha borrado; vuelve a intentarlo."),
            Error::Red(e) => write!(f, "No se pudo descargar el motor de IA: {e}"),
            Error::Servidor(e) => write!(
                f,
                "El servidor del motor de IA no dejó descargarlo ({e}). No es un corte de internet: prueba más tarde o con otra conexión."
            ),
            Error::Disco(e) => write!(f, "No se pudo guardar el motor de IA en el disco: {e}"),
        }
    }
}

impl Error {
    /// Se perdió internet durante la descarga del motor: puede esperar y reanudarse sola. Un código HTTP de error o
    /// un fallo de certificado (`Servidor`), un disco lleno, un paquete dañado o una cancelación no son de red.
    pub fn es_de_red(&self) -> bool {
        matches!(self, Error::Red(_))
    }
}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Disco(e)
    }
}

/// Carpeta donde vive cada versión del motor: `<ia>/motor/<versión>`.
pub fn carpeta(ia: &Path, motor: &Motor) -> PathBuf {
    ia.join("motor").join(&motor.version)
}

/// Ejecutable de Ollama dentro de la carpeta del motor, según la estructura de cada paquete.
pub fn ejecutable(carpeta_motor: &Path) -> PathBuf {
    if cfg!(windows) {
        carpeta_motor.join("ollama.exe")
    } else {
        carpeta_motor.join("bin").join("ollama")
    }
}

pub fn instalado(ia: &Path, motor: &Motor) -> bool {
    let c = carpeta(ia, motor);
    c.join(MARCA_COMPLETO).exists() && ejecutable(&c).exists()
}

/// Instala el motor si no lo está. Devuelve la ruta del ejecutable.
pub fn instalar(
    ia: &Path,
    motor: &Motor,
    cancelar: &AtomicBool,
    progreso: &mut dyn FnMut(Progreso),
) -> Result<PathBuf, Error> {
    if instalado(ia, motor) {
        progreso(Progreso::Listo);
        return Ok(ejecutable(&carpeta(ia, motor)));
    }
    reinstalar(ia, motor, cancelar, progreso)
}

/// Descarga, verifica y extrae el motor aunque ya esté instalado. El motor que hubiera sigue
/// entero hasta el último paso, y vuelve a su sitio si ese paso falla.
fn reinstalar(
    ia: &Path,
    motor: &Motor,
    cancelar: &AtomicBool,
    progreso: &mut dyn FnMut(Progreso),
) -> Result<PathBuf, Error> {
    let destino = carpeta(ia, motor);
    let paquete = motor.paquete().ok_or(Error::SinPaquete)?;
    let descargas = ia.join("descargas");
    fs::create_dir_all(&descargas)?;
    let archivo = descargas.join(&paquete.archivo);

    if !archivo.exists() {
        descargar(&motor.url(paquete), &archivo, cancelar, progreso)?;
    }
    progreso(Progreso::Verificando);
    if sha256(&archivo)? != paquete.sha256.to_ascii_lowercase() {
        fs::remove_file(&archivo)?;
        return Err(Error::Danado);
    }

    progreso(Progreso::Extrayendo);
    let tmp = destino.with_extension("extrayendo");
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp)?;
    if let Err(e) = extraer(&archivo, paquete, &tmp)
        .and_then(|()| Ok(escribir_sumas(&tmp)?))
        .and_then(|()| sustituir(&tmp, &destino))
    {
        let _ = fs::remove_dir_all(&tmp);
        return Err(e);
    }
    fs::remove_file(&archivo)?;
    borrar_versiones_antiguas(ia, motor);

    progreso(Progreso::Listo);
    Ok(ejecutable(&destino))
}

/// «Reparar» (`INS-49`, docs/11): comprueba la suma de cada archivo del motor y, si alguno falta o
/// está dañado, lo vuelve a instalar entero (el «Verificar archivos» de Steam). Devuelve si hubo
/// que reinstalarlo. Un motor sin sumas en `.completo` (instalado antes de que las llevara) no se
/// puede comprobar y también se reinstala.
pub fn reparar(
    ia: &Path,
    motor: &Motor,
    cancelar: &AtomicBool,
    progreso: &mut dyn FnMut(Progreso),
) -> Result<bool, Error> {
    progreso(Progreso::Verificando);
    if integro(ia, motor, cancelar)? {
        progreso(Progreso::Listo);
        return Ok(false);
    }
    reinstalar(ia, motor, cancelar, progreso)?;
    Ok(true)
}

/// El motor está instalado y cada archivo apuntado en `.completo` conserva su suma.
pub fn integro(ia: &Path, motor: &Motor, cancelar: &AtomicBool) -> Result<bool, Error> {
    let c = carpeta(ia, motor);
    let Ok(sumas) = fs::read_to_string(c.join(MARCA_COMPLETO)) else {
        return Ok(false);
    };
    let mut hay = false;
    for linea in sumas.lines() {
        if cancelar.load(Ordering::Relaxed) {
            return Err(Error::Cancelado);
        }
        let Some((suma, ruta)) = linea.split_once("  ") else {
            return Ok(false);
        };
        if sha256(&c.join(ruta)).ok().as_deref() != Some(suma) {
            return Ok(false);
        }
        hay = true;
    }
    Ok(hay && ejecutable(&c).exists())
}

/// Pone `nuevo` en lugar de `destino`. El motor anterior se aparta entero antes (en Windows falla
/// si algún archivo sigue abierto, y entonces no se ha tocado nada) y vuelve si el cambio falla.
fn sustituir(nuevo: &Path, destino: &Path) -> Result<(), Error> {
    let apartado = destino.with_extension("anterior");
    let _ = fs::remove_dir_all(&apartado);
    let habia = destino.exists();
    if habia {
        fs::rename(destino, &apartado)?;
    }
    if let Err(e) = fs::rename(nuevo, destino) {
        if habia {
            let _ = fs::rename(&apartado, destino);
        }
        return Err(e.into());
    }
    let _ = fs::remove_dir_all(&apartado);
    Ok(())
}

/// Escribe `.completo` con una línea `<sha256>  <ruta relativa>` por archivo, como `sha256sum`.
/// Un enlace simbólico a un archivo (las `.so` del paquete de Linux) se apunta con la suma de su
/// destino: si el enlace falta o se rompe, la comprobación falla.
fn escribir_sumas(carpeta_motor: &Path) -> io::Result<()> {
    let mut archivos = Vec::new();
    listar(carpeta_motor, Path::new(""), &mut archivos)?;
    archivos.sort();
    let mut sumas = String::new();
    for ruta in archivos {
        let relativa = ruta.iter().map(|c| c.to_string_lossy()).collect::<Vec<_>>().join("/");
        sumas.push_str(&format!("{}  {relativa}\n", sha256(&carpeta_motor.join(&ruta))?));
    }
    fs::write(carpeta_motor.join(MARCA_COMPLETO), sumas)
}

fn listar(base: &Path, relativa: &Path, archivos: &mut Vec<PathBuf>) -> io::Result<()> {
    for e in fs::read_dir(base.join(relativa))? {
        let e = e?;
        let ruta = relativa.join(e.file_name());
        let tipo = e.file_type()?;
        if tipo.is_dir() {
            listar(base, &ruta, archivos)?;
        } else if (tipo.is_file() || tipo.is_symlink() && e.path().is_file()) && ruta != Path::new(MARCA_COMPLETO) {
            archivos.push(ruta);
        }
    }
    Ok(())
}

/// Tras actualizar el motor, las versiones anteriores sobran.
fn borrar_versiones_antiguas(ia: &Path, motor: &Motor) {
    let Ok(entradas) = fs::read_dir(ia.join("motor")) else {
        return;
    };
    for e in entradas.flatten() {
        if e.file_name().to_string_lossy() != motor.version {
            let _ = fs::remove_dir_all(e.path());
        }
    }
}

/// Descarga reanudable: continúa `<destino>.part` si existe.
pub fn descargar(
    url: &str,
    destino: &Path,
    cancelar: &AtomicBool,
    progreso: &mut dyn FnMut(Progreso),
) -> Result<(), Error> {
    let parcial = destino.with_extension(format!(
        "{}.part",
        destino.extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default()
    ));
    let mut ya = fs::metadata(&parcial).map(|m| m.len()).unwrap_or(0);

    let respuesta = match pedir(url, ya) {
        // 416: lo que hay en el `.part` no encaja con el archivo del servidor (cambió, o ya estaba entero). Se
        // empieza de cero, una sola vez: si vuelve a fallar, el error sale tal cual.
        Err(ureq::Error::StatusCode(416)) if ya > 0 => {
            fs::remove_file(&parcial)?;
            ya = 0;
            pedir(url, 0)
        }
        r => r,
    }
    .map_err(error_de_peticion)?;
    let reanuda = respuesta.status() == 206;
    let resto: u64 = respuesta
        .headers()
        .get("content-length")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    let (mut hecho, total) = if reanuda { (ya, ya + resto) } else { (0, resto) };

    let mut salida = if reanuda { File::options().append(true).open(&parcial)? } else { File::create(&parcial)? };
    let mut cuerpo = respuesta.into_body().into_reader();
    let mut buf = vec![0u8; 256 * 1024];
    let mut ultimo = 0u64;
    loop {
        if cancelar.load(Ordering::Relaxed) {
            return Err(Error::Cancelado);
        }
        let n = cuerpo.read(&mut buf).map_err(|e| Error::Red(e.to_string()))?;
        if n == 0 {
            break;
        }
        salida.write_all(&buf[..n])?;
        hecho += n as u64;
        // Un aviso cada 4 MB basta para una barra de progreso fluida.
        if hecho - ultimo >= 4 * 1024 * 1024 {
            ultimo = hecho;
            progreso(Progreso::Descargando { hecho, total });
        }
    }
    salida.sync_all()?;
    if total > 0 && hecho < total {
        return Err(Error::Red(format!("la descarga se cortó ({hecho} de {total} bytes); se reanudará")));
    }
    progreso(Progreso::Descargando { hecho, total: total.max(hecho) });
    fs::rename(&parcial, destino)?;
    Ok(())
}

/// Pide `url` desde el byte `desde` (con cabecera Range si no es 0).
fn pedir(url: &str, desde: u64) -> Result<ureq::http::Response<ureq::Body>, ureq::Error> {
    let mut peticion = agente().get(url);
    if desde > 0 {
        peticion = peticion.header("Range", &format!("bytes={desde}-"));
    }
    peticion.call()
}

/// Solo los fallos de transporte son de red (se esperan y se reintentan); un código HTTP o un fallo de TLS no.
fn error_de_peticion(e: ureq::Error) -> Error {
    match e {
        ureq::Error::Io(_) | ureq::Error::Timeout(_) | ureq::Error::HostNotFound | ureq::Error::ConnectionFailed => {
            Error::Red(e.to_string())
        }
        e => Error::Servidor(e.to_string()),
    }
}

/// Cliente HTTP para descargas de internet: respeta el proxy del sistema y usa sus certificados.
pub(crate) fn agente() -> ureq::Agent {
    ureq::Agent::config_builder()
        .tls_config(ureq::tls::TlsConfig::builder().root_certs(ureq::tls::RootCerts::PlatformVerifier).build())
        .build()
        .into()
}

pub fn sha256(fichero: &Path) -> io::Result<String> {
    let mut f = File::open(fichero)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1024 * 1024];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

#[cfg(target_os = "linux")]
fn extraer(archivo: &Path, _: &PaqueteMotor, destino: &Path) -> Result<(), Error> {
    let zst = ruzstd::decoding::StreamingDecoder::new(File::open(archivo)?)
        .map_err(|e| Error::Disco(io::Error::other(e.to_string())))?;
    let mut tar = tar::Archive::new(zst);
    tar.set_preserve_permissions(true);
    tar.unpack(destino)?;
    Ok(())
}

#[cfg(windows)]
fn extraer(archivo: &Path, _: &PaqueteMotor, destino: &Path) -> Result<(), Error> {
    let mut zip =
        zip::ZipArchive::new(File::open(archivo)?).map_err(|e| Error::Disco(io::Error::other(e.to_string())))?;
    zip.extract(destino).map_err(|e| Error::Disco(io::Error::other(e.to_string())))?;
    Ok(())
}

#[cfg(not(any(target_os = "linux", windows)))]
fn extraer(_: &Path, _: &PaqueteMotor, _: &Path) -> Result<(), Error> {
    Err(Error::SinPaquete)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn solo_el_error_de_red_es_de_red() {
        assert!(Error::Red("connection reset".into()).es_de_red());
        assert!(!Error::Cancelado.es_de_red());
        assert!(!Error::Danado.es_de_red());
        assert!(!Error::Servidor("http status: 404".into()).es_de_red());
        assert!(!Error::SinPaquete.es_de_red());
        assert!(!Error::Disco(io::Error::other("sin espacio")).es_de_red());
    }

    /// Sirve `datos` por HTTP; con cabecera Range responde 206 con el resto.
    fn servidor(datos: Vec<u8>) -> String {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let url = format!("http://127.0.0.1:{}/paquete", l.local_addr().unwrap().port());
        thread::spawn(move || {
            for s in l.incoming().flatten() {
                let mut r = BufReader::new(s.try_clone().unwrap());
                let mut desde = 0usize;
                loop {
                    let mut linea = String::new();
                    if r.read_line(&mut linea).unwrap_or(0) == 0 || linea == "\r\n" {
                        break;
                    }
                    if let Some(v) = linea.to_ascii_lowercase().strip_prefix("range: bytes=") {
                        desde = v.trim().trim_end_matches('-').parse().unwrap();
                    }
                }
                let cuerpo = &datos[desde..];
                let estado = if desde > 0 { "206 Partial Content" } else { "200 OK" };
                let mut s = s;
                let _ = write!(s, "HTTP/1.1 {estado}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", cuerpo.len());
                let _ = s.write_all(cuerpo);
            }
        });
        url
    }

    #[test]
    fn descarga_y_reanuda() {
        let datos: Vec<u8> = (0..10_000_000u32).map(|i| (i % 251) as u8).collect();
        let url = servidor(datos.clone());
        let dir = tempfile::tempdir().unwrap();
        let destino = dir.path().join("paquete.tar.zst");
        // Simula un corte: ya hay 3 MB en el .part.
        fs::write(dir.path().join("paquete.tar.zst.part"), &datos[..3_000_000]).unwrap();

        let mut avisos = Vec::new();
        descargar(&url, &destino, &AtomicBool::new(false), &mut |p| avisos.push(p)).unwrap();
        assert_eq!(fs::read(&destino).unwrap(), datos);
        assert_eq!(avisos.last(), Some(&Progreso::Descargando { hecho: 10_000_000, total: 10_000_000 }));
        // Reanudó: el primer aviso ya parte de los 3 MB previos.
        assert!(matches!(avisos[0], Progreso::Descargando { hecho, .. } if hecho > 3_000_000));
    }

    /// Servidor que contesta con los bytes crudos que decida `respuesta(desde)` (el Range pedido, si lo hay);
    /// devuelve la URL y cuántas peticiones recibió.
    fn servidor_crudo(
        respuesta: impl Fn(Option<u64>) -> Vec<u8> + Send + 'static,
    ) -> (String, std::sync::Arc<std::sync::atomic::AtomicUsize>) {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let url = format!("http://127.0.0.1:{}/paquete", l.local_addr().unwrap().port());
        let peticiones = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let cuenta = peticiones.clone();
        thread::spawn(move || {
            for s in l.incoming().flatten() {
                cuenta.fetch_add(1, Ordering::SeqCst);
                let mut r = BufReader::new(s.try_clone().unwrap());
                let mut desde = None;
                loop {
                    let mut linea = String::new();
                    if r.read_line(&mut linea).unwrap_or(0) == 0 || linea == "\r\n" {
                        break;
                    }
                    if let Some(v) = linea.to_ascii_lowercase().strip_prefix("range: bytes=") {
                        desde = Some(v.trim().trim_end_matches('-').parse().unwrap());
                    }
                }
                let mut s = s;
                let _ = s.write_all(&respuesta(desde));
            }
        });
        (url, peticiones)
    }

    #[test]
    fn un_404_no_es_de_red_y_dice_el_codigo() {
        let (url, _) =
            servidor_crudo(|_| b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec());
        let dir = tempfile::tempdir().unwrap();
        let e = descargar(&url, &dir.path().join("x.zip"), &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(matches!(&e, Error::Servidor(m) if m.contains("404")), "{e:?}");
        assert!(!e.es_de_red());
        assert!(e.to_string().contains("No es un corte de internet"), "{e}");
    }

    #[test]
    fn un_416_con_part_borra_el_part_y_empieza_de_cero() {
        let datos: Vec<u8> = (0..50_000u32).map(|i| (i % 251) as u8).collect();
        let cuerpo = datos.clone();
        let (url, peticiones) = servidor_crudo(move |desde| {
            if desde.is_some() {
                return b"HTTP/1.1 416 Range Not Satisfiable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    .to_vec();
            }
            let mut r = format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", cuerpo.len())
                .into_bytes();
            r.extend_from_slice(&cuerpo);
            r
        });
        let dir = tempfile::tempdir().unwrap();
        let destino = dir.path().join("paquete.zip");
        fs::write(dir.path().join("paquete.zip.part"), b"basura de otro archivo").unwrap();
        descargar(&url, &destino, &AtomicBool::new(false), &mut |_| {}).unwrap();
        assert_eq!(fs::read(&destino).unwrap(), datos);
        assert!(!dir.path().join("paquete.zip.part").exists());
        assert_eq!(peticiones.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn un_416_que_se_repite_se_intenta_una_sola_vez_y_no_es_de_red() {
        let (url, peticiones) = servidor_crudo(|_| {
            b"HTTP/1.1 416 Range Not Satisfiable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec()
        });
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("x.zip.part"), b"abc").unwrap();
        let e = descargar(&url, &dir.path().join("x.zip"), &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(matches!(&e, Error::Servidor(m) if m.contains("416")), "{e:?}");
        assert_eq!(peticiones.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn un_corte_a_mitad_del_cuerpo_sigue_siendo_de_red() {
        // Promete 1000 bytes, manda 100 y cierra.
        let (url, _) = servidor_crudo(|_| {
            let mut r = b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n".to_vec();
            r.extend_from_slice(&[7u8; 100]);
            r
        });
        let dir = tempfile::tempdir().unwrap();
        let e = descargar(&url, &dir.path().join("x.zip"), &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(matches!(e, Error::Red(_)), "{e:?}");
        assert!(e.es_de_red());
        // Lo recibido queda en el .part para reanudar.
        assert_eq!(fs::metadata(dir.path().join("x.zip.part")).unwrap().len(), 100);
    }

    #[test]
    fn sin_servidor_es_de_red() {
        // Puerto cerrado: fallo de conexión, que sí se espera y se reintenta.
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let url = format!("http://127.0.0.1:{}/paquete", l.local_addr().unwrap().port());
        drop(l);
        let dir = tempfile::tempdir().unwrap();
        let e = descargar(&url, &dir.path().join("x.zip"), &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(e.es_de_red(), "{e:?}");
    }

    #[test]
    fn se_puede_cancelar() {
        let url = servidor(vec![0u8; 5_000_000]);
        let dir = tempfile::tempdir().unwrap();
        let r = descargar(&url, &dir.path().join("x.zip"), &AtomicBool::new(true), &mut |_| {});
        assert!(matches!(r, Err(Error::Cancelado)));
    }

    #[test]
    fn suma_sha256() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("a");
        fs::write(&f, b"tarkor").unwrap();
        // Valor de referencia: `printf tarkor | sha256sum`.
        assert_eq!(sha256(&f).unwrap(), "00ac1f2c6563a9612dd6d90dd53628eac0fa9a16f79179c87be9f5ebda1ae9f3");
    }

    #[test]
    fn un_paquete_con_otra_suma_se_rechaza_y_se_borra() {
        let url = servidor(b"no es ollama".to_vec());
        let dir = tempfile::tempdir().unwrap();
        let mut motor = crate::catalogo::Catalogo::incrustado().motor;
        let so = std::env::consts::OS.to_string();
        motor.url_base = url.trim_end_matches("paquete").to_string();
        motor.paquetes.insert(so, PaqueteMotor { archivo: "paquete".into(), sha256: "0".repeat(64), descarga_gb: 0.0 });
        let r = instalar(dir.path(), &motor, &AtomicBool::new(false), &mut |_| {});
        assert!(matches!(r, Err(Error::Danado)), "{r:?}");
        assert!(!dir.path().join("descargas/paquete").exists());
        assert!(!instalado(dir.path(), &motor));
    }

    /// Un motor instalado a mano: `bin/ollama` y una biblioteca, con sus sumas.
    fn motor_instalado(ia: &Path) -> Motor {
        let motor = crate::catalogo::Catalogo::incrustado().motor;
        let c = carpeta(ia, &motor);
        fs::create_dir_all(ejecutable(&c).parent().unwrap()).unwrap();
        fs::create_dir_all(c.join("lib/ollama")).unwrap();
        fs::write(ejecutable(&c), b"ollama").unwrap();
        fs::write(c.join("lib/ollama/libggml.so"), b"ggml").unwrap();
        escribir_sumas(&c).unwrap();
        motor
    }

    #[test]
    fn las_sumas_de_cada_archivo_detectan_un_motor_danado() {
        let dir = tempfile::tempdir().unwrap();
        let motor = motor_instalado(dir.path());
        let c = carpeta(dir.path(), &motor);
        let sumas = fs::read_to_string(c.join(MARCA_COMPLETO)).unwrap();
        assert!(sumas.contains("  lib/ollama/libggml.so\n"), "{sumas}");
        assert!(integro(dir.path(), &motor, &AtomicBool::new(false)).unwrap());
        fs::write(c.join("lib/ollama/libggml.so"), b"gml").unwrap();
        assert!(!integro(dir.path(), &motor, &AtomicBool::new(false)).unwrap());
        fs::remove_file(c.join("lib/ollama/libggml.so")).unwrap();
        assert!(!integro(dir.path(), &motor, &AtomicBool::new(false)).unwrap());
    }

    #[test]
    fn un_motor_sin_sumas_no_cuenta_como_integro() {
        let dir = tempfile::tempdir().unwrap();
        let motor = motor_instalado(dir.path());
        fs::write(carpeta(dir.path(), &motor).join(MARCA_COMPLETO), b"").unwrap();
        assert!(instalado(dir.path(), &motor));
        assert!(!integro(dir.path(), &motor, &AtomicBool::new(false)).unwrap());
    }

    #[test]
    fn reparar_un_motor_sano_no_descarga_nada() {
        let dir = tempfile::tempdir().unwrap();
        let mut motor = motor_instalado(dir.path());
        motor.url_base = "http://127.0.0.1:9/".into();
        let mut avisos = Vec::new();
        assert!(!reparar(dir.path(), &motor, &AtomicBool::new(false), &mut |p| avisos.push(p)).unwrap());
        assert_eq!(avisos, [Progreso::Verificando, Progreso::Listo]);
    }

    #[test]
    fn reparar_un_motor_danado_lo_vuelve_a_instalar() {
        let dir = tempfile::tempdir().unwrap();
        let mut motor = motor_instalado(dir.path());
        fs::write(ejecutable(&carpeta(dir.path(), &motor)), b"roto").unwrap();
        // El servidor sirve otro paquete: llega a descargarlo, que es lo que se comprueba aquí.
        let url = servidor(b"no es ollama".to_vec());
        motor.url_base = url.trim_end_matches("paquete").to_string();
        motor.paquetes.insert(
            std::env::consts::OS.into(),
            PaqueteMotor { archivo: "paquete".into(), sha256: "0".repeat(64), descarga_gb: 0.0 },
        );
        let r = reparar(dir.path(), &motor, &AtomicBool::new(false), &mut |_| {});
        assert!(matches!(r, Err(Error::Danado)), "{r:?}");
        // Una reparación que falla no deja sin motor: el de antes sigue instalado como estaba.
        assert!(instalado(dir.path(), &motor));
        assert_eq!(fs::read(ejecutable(&carpeta(dir.path(), &motor))).unwrap(), b"roto");
    }

    #[test]
    fn la_comprobacion_del_motor_se_puede_cancelar() {
        let dir = tempfile::tempdir().unwrap();
        let motor = motor_instalado(dir.path());
        let r = integro(dir.path(), &motor, &AtomicBool::new(true));
        assert!(matches!(r, Err(Error::Cancelado)), "{r:?}");
    }

    #[test]
    fn sustituir_cambia_el_motor_y_lo_devuelve_si_falla() {
        let dir = tempfile::tempdir().unwrap();
        let (nuevo, destino) = (dir.path().join("nuevo"), dir.path().join("0.1"));
        fs::create_dir_all(&destino).unwrap();
        fs::write(destino.join("viejo"), b"v").unwrap();
        // Sin `nuevo`, el cambio falla y el motor de antes vuelve a su sitio.
        assert!(sustituir(&nuevo, &destino).is_err());
        assert!(destino.join("viejo").exists());
        fs::create_dir_all(&nuevo).unwrap();
        fs::write(nuevo.join("nuevo"), b"n").unwrap();
        sustituir(&nuevo, &destino).unwrap();
        assert!(destino.join("nuevo").exists() && !destino.join("viejo").exists());
        assert!(!destino.with_extension("anterior").exists());
    }

    #[cfg(unix)]
    #[test]
    fn un_enlace_roto_del_motor_se_detecta() {
        let dir = tempfile::tempdir().unwrap();
        let motor = crate::catalogo::Catalogo::incrustado().motor;
        let c = carpeta(dir.path(), &motor);
        fs::create_dir_all(ejecutable(&c).parent().unwrap()).unwrap();
        fs::create_dir_all(c.join("lib")).unwrap();
        fs::write(ejecutable(&c), b"ollama").unwrap();
        fs::write(c.join("lib/libcudart.so.12.8"), b"cuda").unwrap();
        std::os::unix::fs::symlink("libcudart.so.12.8", c.join("lib/libcudart.so.12")).unwrap();
        escribir_sumas(&c).unwrap();
        assert!(fs::read_to_string(c.join(MARCA_COMPLETO)).unwrap().contains("  lib/libcudart.so.12\n"));
        fs::remove_file(c.join("lib/libcudart.so.12")).unwrap();
        assert!(!integro(dir.path(), &motor, &AtomicBool::new(false)).unwrap());
    }
}
