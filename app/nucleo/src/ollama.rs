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

/// Traduce los errores de Ollama más habituales a lenguaje de jugador (docs/11, principio 4).
fn explicar(e: &str) -> String {
    let m = e.to_ascii_lowercase();
    if m.contains("memory") || m.contains("oom") {
        format!("Tu equipo se ha quedado sin memoria al cargar el modelo. Prueba un perfil más ligero o cierra otros programas. ({e})")
    } else if m.contains("dial tcp") || m.contains("no such host") || m.contains("connection") || m.contains("timeout") {
        format!("No se pudo conectar con el servidor de modelos. Comprueba tu conexión a internet y vuelve a intentarlo; lo ya descargado se conserva. ({e})")
    } else if m.contains("no space") {
        format!("No queda espacio en el disco para el modelo. ({e})")
    } else {
        format!("El motor de IA ha devuelto un error: {e}")
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
}

pub struct Cliente {
    base: String,
    agente: ureq::Agent,
}

impl Cliente {
    pub fn new(base: impl Into<String>) -> Cliente {
        let agente = ureq::Agent::config_builder()
            .proxy(None)
            .http_status_as_error(false)
            .timeout_connect(Some(Duration::from_secs(3)))
            .build()
            .into();
        Cliente { base: base.into().trim_end_matches('/').to_string(), agente }
    }

    fn get(&self, ruta: &str) -> Result<Value, Error> {
        let mut r = self.agente.get(format!("{}{ruta}", self.base)).call().map_err(|e| Error::SinConexion(e.to_string()))?;
        leer_json(r.status().as_u16(), r.body_mut().read_to_string().map_err(|e| Error::SinConexion(e.to_string()))?)
    }

    fn post(&self, ruta: &str, cuerpo: Value) -> Result<Value, Error> {
        let mut r = self.agente.post(format!("{}{ruta}", self.base)).send_json(cuerpo).map_err(|e| Error::SinConexion(e.to_string()))?;
        leer_json(r.status().as_u16(), r.body_mut().read_to_string().map_err(|e| Error::SinConexion(e.to_string()))?)
    }

    pub fn version(&self) -> Result<String, Error> {
        Ok(self.get("/api/version")?["version"].as_str().unwrap_or_default().to_string())
    }

    /// Modelos ya descargados, con su etiqueta completa (`qwen2.5:7b`).
    pub fn modelos(&self) -> Result<Vec<String>, Error> {
        let v = self.get("/api/tags")?;
        Ok(v["models"].as_array().into_iter().flatten().filter_map(|m| m["name"].as_str().map(String::from)).collect())
    }

    /// Descarga un modelo. Ollama reanuda solo lo que falte si se corta.
    pub fn descargar_modelo(&self, modelo: &str, cancelar: &AtomicBool, progreso: &mut dyn FnMut(ProgresoModelo)) -> Result<(), Error> {
        let r = self
            .agente
            .post(format!("{}/api/pull", self.base))
            .send_json(json!({ "model": modelo, "stream": true }))
            .map_err(|e| Error::SinConexion(e.to_string()))?;
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
            .map_err(|e| Error::SinConexion(e.to_string()))?;
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
                let total = m["size"].as_f64().unwrap_or(0.0);
                let vram = m["size_vram"].as_f64().unwrap_or(0.0);
                Cargado {
                    modelo: m["name"].as_str().unwrap_or_default().to_string(),
                    porcentaje_gpu: if total > 0.0 { (vram / total * 100.0).round().clamp(0.0, 100.0) as u8 } else { 0 },
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
                    "/api/tags" => ("200 OK", r#"{"models":[{"name":"qwen2.5:7b"},{"name":"nomic-embed-text:latest"}]}"#.to_string()),
                    "/api/pull" => ("200 OK", pull.to_string()),
                    "/api/generate" if peticion.contains("no-existe") => ("404 Not Found", r#"{"error":"model 'no-existe' not found"}"#.to_string()),
                    "/api/generate" => ("200 OK", r#"{"response":" La niebla lo cubre todo. ","eval_count":40,"eval_duration":4000000000}"#.to_string()),
                    "/api/ps" => ("200 OK", r#"{"models":[{"name":"qwen2.5:7b","size":1000,"size_vram":750}]}"#.to_string()),
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
        assert_eq!(c.cargados().unwrap(), [Cargado { modelo: "qwen2.5:7b".into(), porcentaje_gpu: 75 }]);
    }

    #[test]
    fn sin_motor_es_sin_conexion() {
        let c = Cliente::new(format!("http://127.0.0.1:{}", crate::procesos::puerto_libre().unwrap()));
        assert!(matches!(c.version(), Err(Error::SinConexion(_))));
    }
}
