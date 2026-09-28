//! Instalación del motor de IA (Ollama) en la carpeta de la app, sin permisos de administrador
//! ni tocar el sistema (docs/03, "Decisión"; fase 0.5 de docs/05).
//!
//! 1. Descarga el paquete oficial de la versión fijada en el catálogo. Si se corta, se reanuda
//!    donde se quedó (`.part` + cabecera Range).
//! 2. Comprueba su SHA256 contra la suma del catálogo. Si no coincide, lo borra y avisa.
//! 3. Lo extrae en una carpeta temporal y la renombra al final: nunca queda un motor a medias.
//! 4. Borra el paquete descargado para no ocupar el doble.

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
    Red(String),
    Disco(io::Error),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::SinPaquete => write!(f, "No hay motor de IA para este sistema operativo."),
            Error::Cancelado => write!(f, "Descarga cancelada. Lo descargado se conserva para continuar."),
            Error::Danado => write!(f, "El motor de IA se descargó dañado. Se ha borrado; vuelve a intentarlo."),
            Error::Red(e) => write!(f, "No se pudo descargar el motor de IA: {e}"),
            Error::Disco(e) => write!(f, "No se pudo guardar el motor de IA en el disco: {e}"),
        }
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
    let destino = carpeta(ia, motor);
    if instalado(ia, motor) {
        progreso(Progreso::Listo);
        return Ok(ejecutable(&destino));
    }
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
    extraer(&archivo, paquete, &tmp)?;
    File::create(tmp.join(MARCA_COMPLETO))?;
    let _ = fs::remove_dir_all(&destino);
    fs::rename(&tmp, &destino)?;
    fs::remove_file(&archivo)?;
    borrar_versiones_antiguas(ia, motor);

    progreso(Progreso::Listo);
    Ok(ejecutable(&destino))
}

/// Tras actualizar el motor, las versiones anteriores sobran.
fn borrar_versiones_antiguas(ia: &Path, motor: &Motor) {
    let Ok(entradas) = fs::read_dir(ia.join("motor")) else { return };
    for e in entradas.flatten() {
        if e.file_name().to_string_lossy() != motor.version {
            let _ = fs::remove_dir_all(e.path());
        }
    }
}

/// Descarga reanudable: continúa `<destino>.part` si existe.
pub fn descargar(url: &str, destino: &Path, cancelar: &AtomicBool, progreso: &mut dyn FnMut(Progreso)) -> Result<(), Error> {
    let parcial = destino.with_extension(format!(
        "{}.part",
        destino.extension().map(|e| e.to_string_lossy().into_owned()).unwrap_or_default()
    ));
    let ya = fs::metadata(&parcial).map(|m| m.len()).unwrap_or(0);

    let mut peticion = agente().get(url);
    if ya > 0 {
        peticion = peticion.header("Range", &format!("bytes={ya}-"));
    }
    let respuesta = peticion.call().map_err(|e| Error::Red(e.to_string()))?;
    let reanuda = respuesta.status() == 206;
    let resto: u64 = respuesta
        .headers()
        .get("content-length")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    let (mut hecho, total) = if reanuda { (ya, ya + resto) } else { (0, resto) };

    let mut salida = if reanuda {
        File::options().append(true).open(&parcial)?
    } else {
        File::create(&parcial)?
    };
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

/// Cliente HTTP para descargas de internet: respeta el proxy del sistema y usa sus certificados.
pub(crate) fn agente() -> ureq::Agent {
    ureq::Agent::config_builder()
        .tls_config(
            ureq::tls::TlsConfig::builder()
                .root_certs(ureq::tls::RootCerts::PlatformVerifier)
                .build(),
        )
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
    let mut zip = zip::ZipArchive::new(File::open(archivo)?).map_err(|e| Error::Disco(io::Error::other(e.to_string())))?;
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
}
