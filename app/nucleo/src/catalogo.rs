//! Catálogo de modelos y perfiles (docs/12-catalogo-y-rendimiento.md).
//!
//! Añadir un modelo o un perfil, o cambiar sus cifras, es editar `app/catalogo/catalogo.json`: no
//! hace falta tocar código. El catálogo se incrusta al compilar y un `catalogo.json` en la carpeta
//! de datos lo sustituye sin recompilar (para probar cambios en un equipo concreto y, más adelante,
//! para recibir catálogos nuevos sin publicar otra versión de la app). Si el fichero externo no es
//! válido se ignora y se usa el incrustado: un catálogo roto nunca deja el juego sin arrancar.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::Path;

pub const VERSION_CATALOGO: u32 = 1;
const INCRUSTADO: &str = include_str!("../../catalogo/catalogo.json");
const NOMBRE_EXTERNO: &str = "catalogo.json";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Reglas {
    pub reserva_minima_gb: f64,
    pub reserva_proporcion: f64,
    pub memoria_juego_gb: f64,
    pub proporcion_vram_util: f64,
    pub margen_comodo_gb: f64,
    pub margen_disco: f64,
    pub contexto_narrador: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Modelo {
    pub descarga_gb: f64,
    pub licencia: String,
    /// Modelo con modo de razonamiento (Qwen 3.x): el backend le manda `think: false`, porque
    /// pensar antes de narrar multiplica el tiempo de cada turno.
    #[serde(default)]
    pub piensa: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Perfil {
    pub id: String,
    pub nombre: String,
    /// Qué resultado esperar, en palabras de jugador. Se muestra en la tarjeta del perfil.
    pub resultado: String,
    /// 1-4, para las marcas de la tarjeta.
    pub calidad: u8,
    pub velocidad: u8,
    /// Pico estimado de memoria solo de la IA.
    pub memoria_gb: f64,
    pub narrador: String,
    pub cronista: String,
    pub sugerencias: String,
    pub embeddings: String,
    pub max_modelos_cargados: u8,
    pub keep_alive: String,
    /// Nunca se recomienda ni cuenta como máximo seguro; se ofrece con una etiqueta.
    #[serde(default)]
    pub experimental: bool,
}

impl Perfil {
    /// Modelos a descargar, sin repetir.
    pub fn modelos(&self) -> Vec<&str> {
        let mut v: Vec<&str> = Vec::new();
        for m in [&self.narrador, &self.cronista, &self.sugerencias, &self.embeddings] {
            if !v.contains(&m.as_str()) {
                v.push(m);
            }
        }
        v
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Catalogo {
    pub version: u32,
    #[serde(default)]
    pub notas: String,
    pub reglas: Reglas,
    pub modelos: BTreeMap<String, Modelo>,
    /// En orden de menos a más exigente.
    pub perfiles: Vec<Perfil>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", tag = "tipo")]
pub enum Origen {
    Incrustado,
    Externo,
    /// Había un `catalogo.json` externo pero no era válido; se usó el incrustado.
    ExternoInvalido { motivo: String },
}

impl Catalogo {
    pub fn incrustado() -> Catalogo {
        let c: Catalogo = serde_json::from_str(INCRUSTADO).expect("catalogo.json incrustado mal formado");
        c.validar().expect("catalogo.json incrustado no válido");
        c
    }

    pub fn desde_json(texto: &str) -> Result<Catalogo, String> {
        let c: Catalogo = serde_json::from_str(texto).map_err(|e| format!("JSON no válido: {e}"))?;
        c.validar()?;
        Ok(c)
    }

    /// El externo de la carpeta de datos si existe y es válido; si no, el incrustado.
    pub fn cargar(carpeta_datos: &Path) -> (Catalogo, Origen) {
        match fs::read_to_string(carpeta_datos.join(NOMBRE_EXTERNO)) {
            Err(_) => (Self::incrustado(), Origen::Incrustado),
            Ok(texto) => match Self::desde_json(&texto) {
                Ok(c) => (c, Origen::Externo),
                Err(motivo) => (Self::incrustado(), Origen::ExternoInvalido { motivo }),
            },
        }
    }

    pub fn perfil(&self, id: &str) -> Option<&Perfil> {
        self.perfiles.iter().find(|p| p.id == id)
    }

    pub fn descarga_gb(&self, perfil: &Perfil) -> f64 {
        perfil.modelos().iter().filter_map(|m| self.modelos.get(*m)).map(|m| m.descarga_gb).sum()
    }

    /// Modelos que necesitan `think: false`.
    pub fn modelos_que_piensan(&self, perfil: &Perfil) -> Vec<String> {
        perfil
            .modelos()
            .into_iter()
            .filter(|m| self.modelos.get(*m).is_some_and(|x| x.piensa))
            .map(String::from)
            .collect()
    }

    pub fn validar(&self) -> Result<(), String> {
        if self.version != VERSION_CATALOGO {
            return Err(format!("versión {} no soportada (esta app entiende la {VERSION_CATALOGO})", self.version));
        }
        if !self.perfiles.iter().any(|p| !p.experimental) {
            return Err("no hay ningún perfil que no sea experimental".into());
        }
        let mut ids = HashSet::new();
        for p in &self.perfiles {
            if !ids.insert(&p.id) {
                return Err(format!("perfil repetido: {}", p.id));
            }
            if !(1..=4).contains(&p.calidad) || !(1..=4).contains(&p.velocidad) {
                return Err(format!("{}: calidad y velocidad van de 1 a 4", p.id));
            }
            if p.memoria_gb <= 0.0 {
                return Err(format!("{}: memoriaGb debe ser mayor que 0", p.id));
            }
            for m in p.modelos() {
                if !self.modelos.contains_key(m) {
                    return Err(format!("{}: el modelo {m} no está en la lista de modelos", p.id));
                }
            }
        }
        let r = &self.reglas;
        if r.reserva_minima_gb < 0.0 || !(0.0..1.0).contains(&r.reserva_proporcion) || r.margen_disco < 1.0 {
            return Err("reglas fuera de rango".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn el_incrustado_es_valido_y_ordenado() {
        let c = Catalogo::incrustado();
        let ids: Vec<&str> = c.perfiles.iter().map(|p| p.id.as_str()).collect();
        assert_eq!(ids, ["minimo", "ligero", "equilibrado", "maximo", "ultra"]);
        let mem: Vec<f64> = c.perfiles.iter().map(|p| p.memoria_gb).collect();
        assert!(mem.windows(2).all(|w| w[0] <= w[1]), "los perfiles deben ir de menos a más memoria");
    }

    #[test]
    fn todos_los_modelos_con_licencia_apache() {
        // docs/08: un modelo con licencia restrictiva no entra en el catálogo sin revisarlo antes.
        let c = Catalogo::incrustado();
        assert!(c.modelos.values().all(|m| m.licencia == "Apache-2.0"));
    }

    #[test]
    fn embeddings_en_todos_los_perfiles() {
        // El juego lo necesita en partida, no solo al indexar (docs/03).
        let c = Catalogo::incrustado();
        assert!(c.perfiles.iter().all(|p| p.embeddings == "nomic-embed-text"));
    }

    #[test]
    fn descarga_sin_repetir_modelos() {
        let c = Catalogo::incrustado();
        let minimo = c.perfil("minimo").unwrap();
        assert_eq!(minimo.modelos(), ["qwen2.5:1.5b-instruct", "nomic-embed-text"]);
        assert!((c.descarga_gb(minimo) - 1.3).abs() < 1e-9);
        let maximo = c.perfil("maximo").unwrap();
        assert!((c.descarga_gb(maximo) - (4.7 + 1.0 + 3.4 + 0.3)).abs() < 1e-9);
    }

    #[test]
    fn modelos_que_piensan() {
        let c = Catalogo::incrustado();
        assert_eq!(c.modelos_que_piensan(c.perfil("equilibrado").unwrap()), Vec::<String>::new());
        assert_eq!(c.modelos_que_piensan(c.perfil("ligero").unwrap()), ["qwen3.5:2b"]);
    }

    #[test]
    fn externo_valido_sustituye_al_incrustado() {
        let dir = tempfile::tempdir().unwrap();
        let mut c = Catalogo::incrustado();
        c.perfiles[0].nombre = "Probar".into();
        fs::write(dir.path().join(NOMBRE_EXTERNO), serde_json::to_string(&c).unwrap()).unwrap();
        let (cargado, origen) = Catalogo::cargar(dir.path());
        assert_eq!(origen, Origen::Externo);
        assert_eq!(cargado.perfiles[0].nombre, "Probar");
    }

    #[test]
    fn externo_invalido_no_rompe_nada() {
        let dir = tempfile::tempdir().unwrap();
        let mut c = Catalogo::incrustado();
        c.perfiles[1].narrador = "modelo-que-no-existe".into();
        fs::write(dir.path().join(NOMBRE_EXTERNO), serde_json::to_string(&c).unwrap()).unwrap();
        let (cargado, origen) = Catalogo::cargar(dir.path());
        assert_eq!(cargado, Catalogo::incrustado());
        assert!(matches!(origen, Origen::ExternoInvalido { motivo } if motivo.contains("modelo-que-no-existe")));
    }

    #[test]
    fn version_futura_se_rechaza() {
        let mut c = Catalogo::incrustado();
        c.version = 2;
        assert!(Catalogo::desde_json(&serde_json::to_string(&c).unwrap()).is_err());
    }
}
