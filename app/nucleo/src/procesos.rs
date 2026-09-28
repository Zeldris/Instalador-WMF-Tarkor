//! Gestor de procesos auxiliares ("sidecars"): Ollama y, en la fase 4, el backend del juego
//! (docs/04-empaquetado-tauri.md, "Procesos" y "Ciclo de vida").
//!
//! - Cada proceso escucha en un puerto libre de 127.0.0.1 elegido al arrancar.
//! - Su salida va a un fichero de registro propio, para poder "Copiar informe" si algo falla.
//! - Si se cae, se reinicia solo **una vez**; si vuelve a caer, queda detenido y la app lo muestra.
//! - Nunca se queda huérfano: en Linux muere si muere la app (`PR_SET_PDEATHSIG`); en Windows va
//!   dentro de un Job Object que el sistema cierra con la app.

use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Un puerto TCP libre en 127.0.0.1, pedido al sistema.
pub fn puerto_libre() -> io::Result<u16> {
    Ok(TcpListener::bind(("127.0.0.1", 0))?.local_addr()?.port())
}

/// Espera hasta que `GET http://127.0.0.1:{puerto}{ruta}` responda 2xx o se agote el tiempo.
pub fn esperar_http(puerto: u16, ruta: &str, limite: Duration) -> bool {
    let fin = Instant::now() + limite;
    while Instant::now() < fin {
        if get_ok(puerto, ruta) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

/// HTTP mínimo a mano: solo para el health-check local, sin dependencias ni proxies.
fn get_ok(puerto: u16, ruta: &str) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], puerto).into(), Duration::from_millis(500)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    if write!(s, "GET {ruta} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").is_err() {
        return false;
    }
    let mut cabecera = [0u8; 12];
    s.read_exact(&mut cabecera).is_ok() && cabecera.starts_with(b"HTTP/1.") && cabecera[9] == b'2'
}

/// Cómo arrancar un proceso auxiliar.
#[derive(Debug, Clone)]
pub struct Especificacion {
    pub nombre: String,
    pub programa: PathBuf,
    pub argumentos: Vec<String>,
    pub entorno: BTreeMap<String, String>,
    pub registro: PathBuf,
    pub puerto: u16,
    /// Ruta a consultar para saber que está listo (p. ej. `/api/version` en Ollama).
    pub ruta_salud: String,
    pub espera_arranque: Duration,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase", tag = "estado")]
pub enum Estado {
    Funcionando,
    /// Se cayó y se ha vuelto a arrancar (se gasta el único reinicio automático).
    Reiniciado,
    /// Se cayó otra vez, o no llegó a arrancar.
    Detenido { motivo: String },
}

pub struct Proceso {
    pub espec: Especificacion,
    hijo: Option<Child>,
    reinicios: u32,
    #[cfg(windows)]
    _trabajo: Option<windows_job::Trabajo>,
}

impl Proceso {
    /// Arranca el proceso y espera a que responda. Si no responde a tiempo, lo para y da error.
    pub fn arrancar(espec: Especificacion) -> io::Result<Proceso> {
        let mut p = Proceso {
            espec,
            hijo: None,
            reinicios: 0,
            #[cfg(windows)]
            _trabajo: windows_job::Trabajo::nuevo().ok(),
        };
        p.lanzar()?;
        Ok(p)
    }

    fn lanzar(&mut self) -> io::Result<()> {
        let e = &self.espec;
        if let Some(dir) = e.registro.parent() {
            fs::create_dir_all(dir)?;
        }
        let log = File::options().create(true).append(true).open(&e.registro)?;
        let mut cmd = Command::new(&e.programa);
        cmd.args(&e.argumentos)
            .envs(&e.entorno)
            .stdin(Stdio::null())
            .stdout(log.try_clone()?)
            .stderr(log);
        morir_con_la_app(&mut cmd);
        let hijo = cmd.spawn()?;
        #[cfg(windows)]
        if let Some(t) = &self._trabajo {
            t.asignar(&hijo);
        }
        self.hijo = Some(hijo);

        if !esperar_http(e.puerto, &e.ruta_salud, e.espera_arranque) {
            let motivo = match self.hijo.as_mut().and_then(|h| h.try_wait().ok().flatten()) {
                Some(st) => format!("{} se cerró al arrancar ({st})", e.nombre),
                None => format!("{} no respondió en {} s", e.nombre, e.espera_arranque.as_secs()),
            };
            self.parar();
            return Err(io::Error::other(motivo));
        }
        Ok(())
    }

    pub fn url(&self) -> String {
        format!("http://127.0.0.1:{}", self.espec.puerto)
    }

    /// Para llamarlo periódicamente: detecta caídas y aplica el único reinicio automático.
    pub fn vigilar(&mut self) -> Estado {
        let caido = match self.hijo.as_mut() {
            None => return Estado::Detenido { motivo: format!("{} no está en marcha", self.espec.nombre) },
            Some(h) => h.try_wait().ok().flatten(),
        };
        let Some(salida) = caido else {
            return if self.reinicios == 0 { Estado::Funcionando } else { Estado::Reiniciado };
        };
        self.hijo = None;
        if self.reinicios >= 1 {
            return Estado::Detenido { motivo: format!("{} se ha cerrado dos veces ({salida})", self.espec.nombre) };
        }
        self.reinicios += 1;
        match self.lanzar() {
            Ok(()) => Estado::Reiniciado,
            Err(e) => Estado::Detenido { motivo: e.to_string() },
        }
    }

    /// Reintento manual desde la pantalla "El motor se ha detenido": vuelve a dar un reinicio.
    pub fn reintentar(&mut self) -> io::Result<()> {
        self.parar();
        self.reinicios = 0;
        self.lanzar()
    }

    pub fn parar(&mut self) {
        if let Some(mut h) = self.hijo.take() {
            let _ = h.kill();
            let _ = h.wait();
        }
    }
}

impl Drop for Proceso {
    fn drop(&mut self) {
        self.parar();
    }
}

#[cfg(target_os = "linux")]
fn morir_con_la_app(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    // SAFETY: prctl es async-signal-safe y no toca memoria del proceso padre.
    unsafe {
        cmd.pre_exec(|| {
            if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) == -1 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
}

#[cfg(windows)]
fn morir_con_la_app(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(any(target_os = "linux", windows)))]
fn morir_con_la_app(_: &mut Command) {}

#[cfg(windows)]
mod windows_job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// Job Object con "matar al cerrar": cuando la app termina (aunque sea de golpe), Windows
    /// cierra el handle y mata todos los procesos asignados.
    pub struct Trabajo(HANDLE);

    // SAFETY: un HANDLE de Job Object se puede usar desde cualquier hilo.
    unsafe impl Send for Trabajo {}

    impl Trabajo {
        pub fn nuevo() -> windows::core::Result<Trabajo> {
            unsafe {
                let h = CreateJobObjectW(None, None)?;
                let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(
                    h,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )?;
                Ok(Trabajo(h))
            }
        }

        pub fn asignar(&self, hijo: &Child) {
            unsafe {
                let _ = AssignProcessToJobObject(self.0, HANDLE(hijo.as_raw_handle()));
            }
        }
    }

    impl Drop for Trabajo {
        fn drop(&mut self) {
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;

    /// Servidor HTTP de juguete que responde 200 a todo, para probar la espera de salud.
    fn servidor_ok() -> u16 {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let puerto = l.local_addr().unwrap().port();
        thread::spawn(move || {
            for mut s in l.incoming().flatten() {
                let mut buf = [0u8; 512];
                let _ = s.read(&mut buf);
                let _ = s.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok");
            }
        });
        puerto
    }

    #[test]
    fn puertos_libres_y_distintos() {
        let a = puerto_libre().unwrap();
        let b = puerto_libre().unwrap();
        assert!(a > 0 && b > 0);
    }

    #[test]
    fn espera_de_salud() {
        let p = servidor_ok();
        assert!(esperar_http(p, "/", Duration::from_secs(2)));
        let cerrado = puerto_libre().unwrap();
        assert!(!esperar_http(cerrado, "/", Duration::from_millis(400)));
    }

    #[cfg(unix)]
    fn espec(dir: &std::path::Path, script: &str, puerto: u16) -> Especificacion {
        Especificacion {
            nombre: "prueba".into(),
            programa: "sh".into(),
            argumentos: vec!["-c".into(), script.into()],
            entorno: BTreeMap::new(),
            registro: dir.join("registros/prueba.log"),
            puerto,
            ruta_salud: "/".into(),
            espera_arranque: Duration::from_secs(2),
        }
    }

    #[cfg(unix)]
    #[test]
    fn no_arranca_si_no_responde_y_lo_explica() {
        let dir = tempfile::tempdir().unwrap();
        let err = Proceso::arrancar(espec(dir.path(), "echo arrancando; exit 3", puerto_libre().unwrap()))
            .err()
            .unwrap();
        assert!(err.to_string().contains("se cerró al arrancar"), "{err}");
        // La salida del proceso queda en su registro.
        let log = fs::read_to_string(dir.path().join("registros/prueba.log")).unwrap();
        assert!(log.contains("arrancando"));
    }

    #[cfg(unix)]
    #[test]
    fn un_reinicio_y_luego_detenido() {
        let dir = tempfile::tempdir().unwrap();
        // "El proceso" es un sleep; la salud la da un servidor de juguete aparte.
        let p = servidor_ok();
        let mut proc = Proceso::arrancar(espec(dir.path(), "sleep 0.3", p)).unwrap();
        assert_eq!(proc.vigilar(), Estado::Funcionando);
        thread::sleep(Duration::from_millis(600));
        assert_eq!(proc.vigilar(), Estado::Reiniciado);
        thread::sleep(Duration::from_millis(600));
        assert!(matches!(proc.vigilar(), Estado::Detenido { motivo } if motivo.contains("dos veces")));
        // El reintento manual da otra oportunidad.
        proc.reintentar().unwrap();
        assert_eq!(proc.vigilar(), Estado::Funcionando);
    }

    #[cfg(unix)]
    #[test]
    fn parar_mata_el_proceso() {
        let dir = tempfile::tempdir().unwrap();
        let mut proc = Proceso::arrancar(espec(dir.path(), "sleep 30", servidor_ok())).unwrap();
        proc.parar();
        assert!(matches!(proc.vigilar(), Estado::Detenido { .. }));
    }
}
