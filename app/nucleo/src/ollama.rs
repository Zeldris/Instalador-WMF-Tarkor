//! Cliente de la API local de Ollama (docs/03 y docs/12): versión, modelos, descarga de modelos
//! con progreso, borrado, narración de prueba con velocidad real y uso de la gráfica.
//!
//! Siempre contra 127.0.0.1 y sin proxy: nada de esto sale del equipo salvo la descarga de modelos,
//! que hace el propio Ollama desde su registro oficial.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

#[derive(Debug)]
pub enum Error {
    /// El motor no responde (no arrancado o caído).
    SinConexion(String),
    /// Ollama respondió con un error (modelo inexistente, sin memoria, sin red...).
    Ollama(String),
    Cancelado,
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::SinConexion(e) => write!(f, "El motor de IA no responde ({e})."),
            Error::Ollama(e) => write!(f, "{}", explicar(e)),
            Error::Cancelado => write!(f, "Descarga cancelada. Lo descargado se conserva para continuar."),
        }
    }
}

/// Clase de un error de Ollama, por su texto. El orden de `clasificar` importa: la memoria primero, luego la red
/// bloqueada y luego la caída de la conexión.
#[derive(Debug, Clone, Copy, PartialEq)]
enum Clase {
    SinMemoria,
    /// Cortafuegos, proxy, antivirus o certificado: reintentar solo no lo arregla.
    RedBloqueada,
    /// Sin internet (DNS, conexión cortada, tiempo agotado): vuelve sola al volver la red.
    SinRed,
    SinEspacio,
    Otro,
}

fn clasificar(e: &str) -> Clase {
    let m = e.to_ascii_lowercase();
    if m.contains("memory") || m.contains("oom") {
        Clase::SinMemoria
    } else if m.contains("forbidden") || m.contains("403") || m.contains("proxy") || m.contains("certificate") {
        Clase::RedBloqueada
    } else if ["dial tcp", "no such host", "connection", "timeout", "unreachable", "max retries exceeded"]
        .iter()
        .any(|p| m.contains(p))
    {
        Clase::SinRed
    } else if m.contains("no space") {
        Clase::SinEspacio
    } else {
        Clase::Otro
    }
}

impl Error {
    /// Se perdió internet (no el motor local, ni un cortafuegos o proxy): la descarga puede esperar y reanudarse
    /// sola al volver la red.
    pub fn es_de_red(&self) -> bool {
        matches!(self, Error::Ollama(e) if clasificar(e) == Clase::SinRed)
    }

    /// El equipo se quedó sin memoria al cargar el modelo: pide un perfil más ligero.
    pub fn sin_memoria(&self) -> bool {
        matches!(self, Error::Ollama(e) if clasificar(e) == Clase::SinMemoria)
    }
}

/// Traduce los errores de Ollama más habituales a lenguaje de jugador (docs/11, principio 4).
fn explicar(e: &str) -> String {
    match clasificar(e) {
        Clase::SinMemoria => format!("Tu equipo se ha quedado sin memoria al cargar el modelo. Prueba un perfil más ligero o cierra otros programas. ({e})"),
        Clase::RedBloqueada => format!("La red de este equipo no deja descargar del servidor de modelos (puede ser un cortafuegos, un proxy o un antivirus). Prueba con otra conexión; lo ya descargado se conserva. ({e})"),
        Clase::SinRed => format!("No se pudo conectar con el servidor de modelos. Comprueba tu conexión a internet y vuelve a intentarlo; lo ya descargado se conserva. ({e})"),
        Clase::SinEspacio => format!("No queda espacio en el disco para el modelo. ({e})"),
        Clase::Otro => format!("El motor de IA ha devuelto un error: {e}"),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgresoModelo {
    pub modelo: String,
    pub estado: String,
    pub hecho: u64,
    pub total: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Prueba {
    pub texto: String,
    pub tokens_por_segundo: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Cargado {
    pub modelo: String,
    /// 0-100: parte del modelo que está en la gráfica.
    pub porcentaje_gpu: u8,
    /// Memoria que ocupa cargado, en MB (`size` de `/api/ps`).
    pub memoria_mb: u64,
    /// Bytes exactos de `size` y de `size_vram`: `resumen_uso` pesa por ellos, no por el porcentaje
    /// redondeado. No se serializan.
    #[serde(skip)]
    pub tamano_bytes: u64,
    #[serde(skip)]
    pub vram_bytes: u64,
}

const MB: u64 = 1024 * 1024;

/// Dónde corre la IA ahora mismo, con todos los modelos cargados juntos (docs/11, «Dónde corre la IA»).
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Uso {
    /// Parte de la memoria de los modelos que está en la gráfica, pesada por su tamaño. `None` si
    /// no hay nada cargado.
    pub porcentaje_gpu: Option<u8>,
    pub memoria_mb: u64,
}

/// Resume `/api/ps`: porcentaje en la gráfica = suma de `size_vram` / suma de `size`.
pub fn resumen_uso(cargados: &[Cargado]) -> Uso {
    let total: u64 = cargados.iter().map(|c| c.tamano_bytes).sum();
    let vram: u64 = cargados.iter().map(|c| c.vram_bytes.min(c.tamano_bytes)).sum();
    Uso {
        porcentaje_gpu: (total > 0).then(|| (vram as f64 / total as f64 * 100.0).round().clamp(0.0, 100.0) as u8),
        memoria_mb: total / MB,
    }
}

/// `nomic-embed-text` aparece en Ollama como `nomic-embed-text:latest`.
pub fn tiene(hay: &[String], modelo: &str) -> bool {
    hay.iter().any(|h| h == modelo || h.strip_suffix(":latest") == Some(modelo))
}

/// Modelos descargados que no son de ninguno de `del_perfil` (con el sufijo `:latest` de `tiene`).
pub fn sobrantes(hay: Vec<(String, u64)>, del_perfil: &[&str]) -> Vec<(String, u64)> {
    hay.into_iter()
        .filter(|(h, _)| !del_perfil.iter().any(|m| tiene(std::slice::from_ref(h), m)))
        .collect()
}

/// Tiempo máximo de espera de lectura de las peticiones cortas (`/api/ps`, `/api/tags`...): un Ollama
/// que acepta la conexión y no contesta no deja colgado al sondeo.
const ESPERA_LECTURA: Duration = Duration::from_secs(10);

pub struct Cliente {
    base: String,
    /// Peticiones cortas, con tiempo de espera de lectura.
    agente: ureq::Agent,
    /// Descargas en streaming (`/api/pull`) y generación (`/api/generate`, que puede tardar en
    /// cargar el modelo): sin tiempo de espera de lectura.
    agente_largo: ureq::Agent,
}

/// Un fallo de `ureq`; el de tiempo de espera lo dice con esas palabras.
fn sin_conexion(e: ureq::Error) -> Error {
    match e {
        ureq::Error::Timeout(_) => Error::SinConexion("tiempo de espera agotado: el motor aceptó la conexión pero no respondió".into()),
        e => Error::SinConexion(e.to_string()),
    }
}

impl Cliente {
    pub fn new(base: impl Into<String>) -> Cliente {
        Cliente::con_espera(base, ESPERA_LECTURA)
    }

    /// Como `new`, con otro tiempo de espera de lectura para las peticiones cortas.
    pub fn con_espera(base: impl Into<String>, espera: Duration) -> Cliente {
        let base_config = || ureq::Agent::config_builder().proxy(None).http_status_as_error(false).timeout_connect(Some(Duration::from_secs(3)));
        let agente = base_config().timeout_recv_response(Some(espera)).timeout_recv_body(Some(espera)).build().into();
        let agente_largo = base_config().build().into();
        Cliente { base: base.into().trim_end_matches('/').to_string(), agente, agente_largo }
    }

    fn get(&self, ruta: &str) -> Result<Value, Error> {
        let mut r = self.agente.get(format!("{}{ruta}", self.base)).call().map_err(sin_conexion)?;
        leer_json(r.status().as_u16(), r.body_mut().read_to_string().map_err(sin_conexion)?)
    }

    fn post(&self, ruta: &str, cuerpo: Value) -> Result<Value, Error> {
        let mut r = self.agente_largo.post(format!("{}{ruta}", self.base)).send_json(cuerpo).map_err(sin_conexion)?;
        leer_json(r.status().as_u16(), r.body_mut().read_to_string().map_err(sin_conexion)?)
    }

    pub fn version(&self) -> Result<String, Error> {
        Ok(self.get("/api/version")?["version"].as_str().unwrap_or_default().to_string())
    }

    /// Modelos ya descargados, con su etiqueta completa (`qwen2.5:7b`).
    pub fn modelos(&self) -> Result<Vec<String>, Error> {
        let v = self.get("/api/tags")?;
        Ok(v["models"].as_array().into_iter().flatten().filter_map(|m| m["name"].as_str().map(String::from)).collect())
    }

    /// Modelos descargados con su tamaño en disco, en bytes (`/api/tags`).
    pub fn modelos_con_tamano(&self) -> Result<Vec<(String, u64)>, Error> {
        let v = self.get("/api/tags")?;
        Ok(v["models"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|m| Some((m["name"].as_str()?.to_string(), m["size"].as_u64().unwrap_or(0))))
            .collect())
    }

    /// Descarga un modelo. Ollama reanuda solo lo que falte si se corta.
    pub fn descargar_modelo(&self, modelo: &str, cancelar: &AtomicBool, progreso: &mut dyn FnMut(ProgresoModelo)) -> Result<(), Error> {
        let r = self
            .agente_largo
            .post(format!("{}/api/pull", self.base))
            .send_json(json!({ "model": modelo, "stream": true }))
            .map_err(sin_conexion)?;
        let estado_http = r.status().as_u16();
        let lector = BufReader::new(r.into_body().into_reader());
        // Ollama informa por capas (digest); el progreso del modelo es la suma de todas.
        let mut capas: BTreeMap<String, (u64, u64)> = BTreeMap::new();
        let mut ultimo = String::new();
        for linea in lector.lines() {
            if cancelar.load(Ordering::Relaxed) {
                return Err(Error::Cancelado);
            }
            let linea = linea.map_err(|e| Error::SinConexion(e.to_string()))?;
            if linea.trim().is_empty() {
                continue;
            }
            let v: Value = serde_json::from_str(&linea).map_err(|e| Error::Ollama(format!("respuesta no válida: {e}")))?;
            if let Some(err) = v["error"].as_str() {
                return Err(Error::Ollama(err.to_string()));
            }
            let estado = v["status"].as_str().unwrap_or_default().to_string();
            if let (Some(d), Some(t)) = (v["digest"].as_str(), v["total"].as_u64()) {
                capas.insert(d.to_string(), (v["completed"].as_u64().unwrap_or(0), t));
            }
            let (hecho, total) = capas.values().fold((0, 0), |(h, t), (a, b)| (h + a, t + b));
            ultimo = estado.clone();
            progreso(ProgresoModelo { modelo: modelo.to_string(), estado, hecho, total });
        }
        if estado_http >= 400 {
            return Err(Error::Ollama(format!("HTTP {estado_http}")));
        }
        if ultimo != "success" {
            return Err(Error::Ollama("la descarga terminó sin completarse".into()));
        }
        Ok(())
    }

    pub fn borrar_modelo(&self, modelo: &str) -> Result<(), Error> {
        let mut r = self
            .agente
            .delete(format!("{}/api/delete", self.base))
            .force_send_body()
            .send_json(json!({ "model": modelo }))
            .map_err(sin_conexion)?;
        let st = r.status().as_u16();
        if st >= 400 {
            let texto = r.body_mut().read_to_string().unwrap_or_default();
            return Err(Error::Ollama(texto));
        }
        Ok(())
    }

    /// Narración corta de prueba. La velocidad sale de los contadores de Ollama (`eval_count` /
    /// `eval_duration`), no de un cronómetro, así que no cuenta la carga del modelo.
    pub fn probar(&self, modelo: &str, piensa: bool, hilos: usize) -> Result<Prueba, Error> {
        let mut cuerpo = json!({
            "model": modelo,
            "prompt": "Describe en una sola frase, en castellano, el estrecho cubierto de niebla entre dos continentes en guerra.",
            "stream": false,
            "options": { "num_predict": 60, "num_thread": hilos },
        });
        if piensa {
            cuerpo["think"] = json!(false);
        }
        let v = self.post("/api/generate", cuerpo)?;
        let tokens = v["eval_count"].as_f64().unwrap_or(0.0);
        let ns = v["eval_duration"].as_f64().unwrap_or(0.0);
        Ok(Prueba {
            texto: v["response"].as_str().unwrap_or_default().trim().to_string(),
            tokens_por_segundo: if ns > 0.0 { tokens / (ns / 1e9) } else { 0.0 },
        })
    }

    /// Carga un modelo en memoria sin generar nada, para que el primer turno no espere la carga.
    pub fn calentar(&self, modelo: &str) -> Result<(), Error> {
        self.post("/api/generate", json!({ "model": modelo }))?;
        Ok(())
    }

    /// Modelos cargados ahora mismo y qué parte está en la gráfica (`/api/ps`).
    pub fn cargados(&self) -> Result<Vec<Cargado>, Error> {
        let v = self.get("/api/ps")?;
        Ok(v["models"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|m| {
                let tamano_bytes = m["size"].as_u64().unwrap_or(0);
                let vram_bytes = m["size_vram"].as_u64().unwrap_or(0);
                Cargado {
                    modelo: m["name"].as_str().unwrap_or_default().to_string(),
                    porcentaje_gpu: if tamano_bytes > 0 {
                        (vram_bytes as f64 / tamano_bytes as f64 * 100.0).round().clamp(0.0, 100.0) as u8
                    } else {
                        0
                    },
                    memoria_mb: tamano_bytes / MB,
                    tamano_bytes,
                    vram_bytes,
                }
            })
            .collect())
    }
}

fn leer_json(estado: u16, texto: String) -> Result<Value, Error> {
    let v: Value = serde_json::from_str(&texto).unwrap_or(Value::Null);
    if estado >= 400 {
        return Err(Error::Ollama(v["error"].as_str().map(String::from).unwrap_or(texto)));
    }
    Ok(v)
}

/// Para deserializar la respuesta de `/api/version` en otros módulos si hiciera falta.
#[derive(Debug, Deserialize)]
pub struct Version {
    pub version: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;

    /// Imita las rutas de la API de Ollama que usa la app.
    fn ollama_falso(pull: &'static str) -> Cliente {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let base = format!("http://127.0.0.1:{}", l.local_addr().unwrap().port());
        thread::spawn(move || {
            for mut s in l.incoming().flatten() {
                let peticion = leer_peticion(&mut s);
                let ruta = peticion.split_whitespace().nth(1).unwrap_or("").to_string();
                let (estado, cuerpo) = match ruta.as_str() {
                    "/api/version" => ("200 OK", r#"{"version":"0.34.3"}"#.to_string()),
                    "/api/tags" => ("200 OK", r#"{"models":[{"name":"qwen2.5:7b","size":4700000000},{"name":"nomic-embed-text:latest","size":274000000}]}"#.to_string()),
                    "/api/pull" => ("200 OK", pull.to_string()),
                    "/api/generate" if peticion.contains("no-existe") => ("404 Not Found", r#"{"error":"model 'no-existe' not found"}"#.to_string()),
                    "/api/generate" => ("200 OK", r#"{"response":" La niebla lo cubre todo. ","eval_count":40,"eval_duration":4000000000}"#.to_string()),
                    "/api/ps" => ("200 OK", r#"{"models":[{"name":"qwen2.5:7b","size":4194304000,"size_vram":3145728000}]}"#.to_string()),
                    _ => ("404 Not Found", "{}".to_string()),
                };
                let _ = write!(s, "HTTP/1.1 {estado}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{cuerpo}", cuerpo.len());
            }
        });
        Cliente::new(base)
    }

    /// Lee cabeceras y cuerpo completos (el cuerpo puede llegar en otro paquete TCP).
    fn leer_peticion(s: &mut std::net::TcpStream) -> String {
        let mut datos = Vec::new();
        let mut buf = [0u8; 4096];
        loop {
            let n = s.read(&mut buf).unwrap_or(0);
            if n == 0 {
                break;
            }
            datos.extend_from_slice(&buf[..n]);
            let texto = String::from_utf8_lossy(&datos).to_string();
            if let Some(fin) = texto.find("\r\n\r\n") {
                let largo = texto[..fin]
                    .lines()
                    .find_map(|l| l.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap_or(0)))
                    .unwrap_or(0);
                if datos.len() >= fin + 4 + largo {
                    return texto;
                }
            }
        }
        String::from_utf8_lossy(&datos).to_string()
    }

    const PULL_OK: &str = concat!(
        "{\"status\":\"pulling manifest\"}\n",
        "{\"status\":\"pulling a\",\"digest\":\"sha256:a\",\"total\":100,\"completed\":50}\n",
        "{\"status\":\"pulling b\",\"digest\":\"sha256:b\",\"total\":300,\"completed\":300}\n",
        "{\"status\":\"pulling a\",\"digest\":\"sha256:a\",\"total\":100,\"completed\":100}\n",
        "{\"status\":\"verifying sha256 digest\"}\n",
        "{\"status\":\"success\"}\n",
    );

    #[test]
    fn version_y_modelos() {
        let c = ollama_falso(PULL_OK);
        assert_eq!(c.version().unwrap(), "0.34.3");
        assert_eq!(c.modelos().unwrap(), ["qwen2.5:7b", "nomic-embed-text:latest"]);
    }

    #[test]
    fn descarga_suma_el_progreso_de_todas_las_capas() {
        let c = ollama_falso(PULL_OK);
        let mut avisos = Vec::new();
        c.descargar_modelo("qwen2.5:7b", &AtomicBool::new(false), &mut |p| avisos.push((p.hecho, p.total))).unwrap();
        assert!(avisos.contains(&(50, 100)));
        assert!(avisos.contains(&(350, 400)));
        assert_eq!(avisos.last(), Some(&(400, 400)));
    }

    #[test]
    fn error_de_red_explicado_al_jugador() {
        let c = ollama_falso("{\"status\":\"pulling manifest\"}\n{\"error\":\"pull model manifest: dial tcp: lookup registry.ollama.ai: no such host\"}\n");
        let e = c.descargar_modelo("qwen2.5:7b", &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(e.to_string().starts_with("No se pudo conectar con el servidor de modelos"), "{e}");
    }

    #[test]
    fn red_bloqueada_explicada_al_jugador() {
        // Mensaje real de Ollama 0.34.3 detrás de un proxy que bloquea el registro.
        let c = ollama_falso("{\"error\":\"pull model manifest: Get \\\"https://registry.ollama.ai/v2/library/qwen2.5/manifests/1.5b-instruct\\\": Forbidden\"}\n");
        let e = c.descargar_modelo("qwen2.5:1.5b-instruct", &AtomicBool::new(false), &mut |_| {}).unwrap_err();
        assert!(e.to_string().starts_with("La red de este equipo no deja descargar"), "{e}");
    }

    #[test]
    fn predicados_de_clase_de_error() {
        let o = |m: &str| Error::Ollama(m.to_string());
        // Sin red: DNS, conexión cortada, tiempo agotado, red inalcanzable, reintentos agotados.
        for m in [
            "pull model manifest: dial tcp: lookup registry.ollama.ai: no such host",
            "read tcp 10.0.0.2:5000->1.2.3.4:443: connection reset by peer",
            "net/http: TLS handshake timeout",
            "dial tcp 1.2.3.4:443: connect: network is unreachable",
            "max retries exceeded: EOF",
        ] {
            assert!(o(m).es_de_red(), "{m}");
            assert!(!o(m).sin_memoria(), "{m}");
        }
        // Red bloqueada: reintentar solo no lo arregla, no se autopausa.
        for m in ["Get \"https://registry.ollama.ai/v2\": Forbidden", "proxyconnect tcp: connection refused", "x509: certificate signed by unknown authority", "unexpected status 403"] {
            assert!(!o(m).es_de_red(), "{m}");
        }
        // Sin memoria (tiene prioridad sobre "connection" en el mismo texto).
        assert!(o("model requires more system memory").sin_memoria());
        assert!(!o("model requires more system memory").es_de_red());
        assert!(o("out of memory while connection open").sin_memoria());
        assert!(!o("out of memory while connection open").es_de_red());
        // Otros errores.
        assert!(!o("write /x: no space left on device").es_de_red());
        assert!(!o("write /x: no space left on device").sin_memoria());
        // El motor local caído no es de red; la cancelación tampoco.
        assert!(!Error::SinConexion("connection refused".into()).es_de_red());
        assert!(!Error::SinConexion("connection refused".into()).sin_memoria());
        assert!(!Error::Cancelado.es_de_red());
        assert!(!Error::Cancelado.sin_memoria());
    }

    #[test]
    fn descarga_incompleta_es_error() {
        let c = ollama_falso("{\"status\":\"pulling manifest\"}\n");
        assert!(c.descargar_modelo("x", &AtomicBool::new(false), &mut |_| {}).is_err());
    }

    #[test]
    fn prueba_mide_tokens_por_segundo() {
        let c = ollama_falso(PULL_OK);
        let p = c.probar("qwen2.5:7b", false, 4).unwrap();
        assert_eq!(p.texto, "La niebla lo cubre todo.");
        assert_eq!(p.tokens_por_segundo, 10.0);
        assert!(matches!(c.probar("no-existe", false, 4), Err(Error::Ollama(e)) if e.contains("not found")));
    }

    #[test]
    fn porcentaje_en_gpu() {
        let c = ollama_falso(PULL_OK);
        let ps = c.cargados().unwrap();
        assert_eq!(
            ps,
            [Cargado { modelo: "qwen2.5:7b".into(), porcentaje_gpu: 75, memoria_mb: 4000, tamano_bytes: 4_194_304_000, vram_bytes: 3_145_728_000 }]
        );
        assert_eq!(resumen_uso(&ps), Uso { porcentaje_gpu: Some(75), memoria_mb: 4000 });
    }

    fn cargado(tamano_bytes: u64, vram_bytes: u64) -> Cargado {
        Cargado { modelo: "m".into(), porcentaje_gpu: 0, memoria_mb: 0, tamano_bytes, vram_bytes }
    }

    #[test]
    fn resumen_sin_nada_cargado_no_da_porcentaje() {
        assert_eq!(resumen_uso(&[]), Uso { porcentaje_gpu: None, memoria_mb: 0 });
        // Un modelo de tamaño 0 (respuesta rara) tampoco: no se divide entre cero.
        assert_eq!(resumen_uso(&[cargado(0, 0)]).porcentaje_gpu, None);
    }

    #[test]
    fn resumen_pesa_por_tamano_y_no_por_porcentaje() {
        // 100 % de un modelo de 1 MB y 0 % de uno de 3 MB: 25 % en total, no la media (50 %).
        let u = resumen_uso(&[cargado(MB, MB), cargado(3 * MB, 0)]);
        assert_eq!(u, Uso { porcentaje_gpu: Some(25), memoria_mb: 4 });
        // Redondeo: 2/3 = 66,7 -> 67; y la VRAM nunca cuenta más que el tamaño.
        assert_eq!(resumen_uso(&[cargado(3 * MB, 2 * MB)]).porcentaje_gpu, Some(67));
        assert_eq!(resumen_uso(&[cargado(MB, 5 * MB)]).porcentaje_gpu, Some(100));
    }

    #[test]
    fn modelos_con_su_tamano() {
        let c = ollama_falso(PULL_OK);
        assert_eq!(
            c.modelos_con_tamano().unwrap(),
            [("qwen2.5:7b".to_string(), 4_700_000_000), ("nomic-embed-text:latest".to_string(), 274_000_000)]
        );
    }

    #[test]
    fn sobrantes_respeta_el_sufijo_latest() {
        let hay = vec![("qwen2.5:7b".to_string(), 5), ("nomic-embed-text:latest".to_string(), 1), ("llama3:8b".to_string(), 7)];
        let s = sobrantes(hay.clone(), &["qwen2.5:7b", "nomic-embed-text"]);
        assert_eq!(s, [("llama3:8b".to_string(), 7)]);
        // Con otro perfil, sobran el narrador y el de embeddings.
        let s = sobrantes(hay, &["llama3:8b", "nomic-embed-text"]);
        assert_eq!(s, [("qwen2.5:7b".to_string(), 5)]);
        // Un nombre que solo empieza igual no es el mismo modelo.
        assert_eq!(sobrantes(vec![("qwen2.5:7b-instruct".to_string(), 1)], &["qwen2.5:7b"]).len(), 1);
    }

    #[test]
    fn sin_motor_es_sin_conexion() {
        let c = Cliente::new(format!("http://127.0.0.1:{}", crate::procesos::puerto_libre().unwrap()));
        assert!(matches!(c.version(), Err(Error::SinConexion(_))));
    }

    #[test]
    fn un_motor_que_no_responde_falla_por_tiempo() {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let c = Cliente::con_espera(format!("http://127.0.0.1:{}", l.local_addr().unwrap().port()), Duration::from_millis(300));
        // Acepta la conexión y no contesta; se guarda para que no se cierre.
        let aceptador = thread::spawn(move || {
            let s = l.accept().unwrap();
            thread::sleep(Duration::from_secs(3));
            drop(s);
        });
        let inicio = std::time::Instant::now();
        let e = c.cargados().unwrap_err();
        assert!(inicio.elapsed() < Duration::from_secs(2), "tardó {:?}", inicio.elapsed());
        match e {
            Error::SinConexion(m) => assert!(m.contains("tiempo de espera"), "{m}"),
            otro => panic!("error inesperado: {otro:?}"),
        }
        drop(aceptador);
    }
}
