//! Evaluación de los perfiles del catálogo para un equipo y cálculo del máximo seguro
//! (docs/09-deteccion-de-equipo-y-perfiles.md). Las cifras y los perfiles viven en el catálogo
//! (`catalogo.rs`); aquí solo está la lógica.

use crate::catalogo::{Catalogo, Perfil, Reglas};
use crate::equipo::Equipo;
use serde::{Deserialize, Serialize};

const MB_POR_GB: f64 = 1024.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum UsoCpu {
    #[default]
    Moderado,
    Alto,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PerfilEvaluado {
    #[serde(flatten)]
    pub perfil: Perfil,
    pub descarga_gb: f64,
    pub cabe_en_memoria: bool,
    pub cabe_en_disco: bool,
}

impl PerfilEvaluado {
    pub fn cabe(&self) -> bool {
        self.cabe_en_memoria && self.cabe_en_disco
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Evaluacion {
    /// `None` si el jugador eligió "a mano" (sin análisis).
    pub memoria_para_ia_gb: Option<f64>,
    pub perfiles: Vec<PerfilEvaluado>,
    pub maximo_seguro: Option<String>,
    pub recomendado: String,
    /// Se analizó el equipo y no cabe ni el perfil más ligero. Aun así se deja probar el más
    /// ligero: la detección puede equivocarse y la idea es que cualquiera pueda jugar.
    pub equipo_insuficiente: bool,
}

/// Memoria que el equipo puede dedicar a la IA sin quedarse corto.
pub fn memoria_para_ia_gb(reglas: &Reglas, equipo: &Equipo) -> f64 {
    let ram = equipo.ram_total_mb as f64 / MB_POR_GB;
    let reserva = reglas.reserva_minima_gb.max(ram * reglas.reserva_proporcion);
    let mut para_ia = ram - reserva - reglas.memoria_juego_gb;
    if let Some(vram) = equipo.gpu_dedicada().and_then(|g| g.vram_mb) {
        para_ia += vram as f64 / MB_POR_GB * reglas.proporcion_vram_util;
    }
    para_ia.max(0.0)
}

/// Evalúa los perfiles del catálogo para un equipo, o sin equipo si se eligió a mano.
pub fn evaluar(catalogo: &Catalogo, equipo: Option<&Equipo>) -> Evaluacion {
    let reglas = &catalogo.reglas;
    let para_ia = equipo.map(|e| memoria_para_ia_gb(reglas, e));
    let disco_gb = equipo.map(|e| e.disco_libre_mb as f64 / MB_POR_GB);

    let perfiles: Vec<PerfilEvaluado> = catalogo
        .perfiles
        .iter()
        .map(|p| {
            let descarga_gb = catalogo.descarga_gb(p);
            PerfilEvaluado {
                cabe_en_memoria: para_ia.is_none_or(|m| p.memoria_gb <= m),
                cabe_en_disco: disco_gb.is_none_or(|d| descarga_gb * reglas.margen_disco <= d),
                descarga_gb,
                perfil: p.clone(),
            }
        })
        .collect();

    let mas_ligero = perfiles
        .iter()
        .find(|p| !p.perfil.experimental)
        .map(|p| p.perfil.id.clone())
        .expect("el catálogo validado tiene al menos un perfil no experimental");

    let Some(para_ia) = para_ia else {
        return Evaluacion { memoria_para_ia_gb: None, perfiles, maximo_seguro: None, recomendado: mas_ligero, equipo_insuficiente: false };
    };

    let caben: Vec<&PerfilEvaluado> = perfiles.iter().filter(|p| p.cabe() && !p.perfil.experimental).collect();
    let maximo = caben.last().map(|p| p.perfil.id.clone());
    let recomendado = match caben.as_slice() {
        [] => mas_ligero,
        [.., anterior, ultimo] if para_ia - ultimo.perfil.memoria_gb < reglas.margen_comodo_gb => anterior.perfil.id.clone(),
        [.., ultimo] => ultimo.perfil.id.clone(),
    };

    Evaluacion {
        memoria_para_ia_gb: Some(para_ia),
        equipo_insuficiente: maximo.is_none(),
        perfiles,
        maximo_seguro: maximo,
        recomendado,
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::equipo::{Fabricante, Gpu};

    pub fn equipo(ram_gb: u64, vram_gb: Option<u64>, disco_gb: u64) -> Equipo {
        let gpus = match vram_gb {
            Some(v) => vec![Gpu { nombre: "dedicada".into(), fabricante: Fabricante::Nvidia, vram_mb: Some(v * 1024), integrada: false }],
            None => vec![Gpu { nombre: "integrada".into(), fabricante: Fabricante::Amd, vram_mb: None, integrada: true }],
        };
        Equipo {
            ram_total_mb: ram_gb * 1024,
            ram_libre_mb: ram_gb * 512,
            cpu_modelo: "prueba".into(),
            nucleos: 4,
            hilos: 8,
            gpus,
            disco_libre_mb: disco_gb * 1024,
            sistema: "prueba".into(),
        }
    }

    fn ev(ram: u64, vram: Option<u64>, disco: u64) -> Evaluacion {
        evaluar(&Catalogo::incrustado(), Some(&equipo(ram, vram, disco)))
    }

    // Ejemplos de la tabla de docs/09.

    #[test]
    fn equipo_4gb_prueba_con_minimo() {
        let e = ev(4, None, 50);
        assert_eq!(e.memoria_para_ia_gb, Some(0.0));
        assert!(e.equipo_insuficiente);
        assert_eq!(e.recomendado, "minimo");
    }

    #[test]
    fn equipo_6gb_minimo() {
        let e = ev(6, None, 100);
        assert_eq!(e.memoria_para_ia_gb, Some(2.0));
        assert_eq!(e.maximo_seguro.as_deref(), Some("minimo"));
        assert_eq!(e.recomendado, "minimo");
        assert!(!e.equipo_insuficiente);
    }

    #[test]
    fn portatil_8gb_ligero_justo_recomienda_minimo() {
        let e = ev(8, None, 100);
        assert_eq!(e.memoria_para_ia_gb, Some(4.0));
        assert_eq!(e.maximo_seguro.as_deref(), Some("ligero"));
        assert_eq!(e.recomendado, "minimo");
    }

    #[test]
    fn deck_16gb_maximo_justo_recomienda_equilibrado() {
        let e = ev(16, None, 200);
        assert_eq!(e.memoria_para_ia_gb, Some(11.0));
        assert_eq!(e.maximo_seguro.as_deref(), Some("maximo"));
        assert_eq!(e.recomendado, "equilibrado");
    }

    #[test]
    fn pc_16gb_con_gpu_8gb_recomienda_maximo() {
        let e = ev(16, Some(8), 400);
        let m = e.memoria_para_ia_gb.unwrap();
        assert!((m - 18.2).abs() < 0.01, "{m}");
        assert_eq!(e.maximo_seguro.as_deref(), Some("maximo"));
        assert_eq!(e.recomendado, "maximo");
    }

    #[test]
    fn experimental_nunca_se_recomienda_aunque_quepa() {
        let e = ev(64, Some(24), 500);
        let ultra = e.perfiles.iter().find(|p| p.perfil.id == "ultra").unwrap();
        assert!(ultra.cabe());
        assert_eq!(e.maximo_seguro.as_deref(), Some("maximo"));
        assert_eq!(e.recomendado, "maximo");
    }

    #[test]
    fn el_disco_tambien_limita() {
        // Memoria de sobra pero solo 8 GB libres: Máximo necesita 9,4 × 1,1 GB y no cabe;
        // Equilibrado necesita 6 × 1,1 = 6,6 GB y sí.
        let e = ev(32, Some(12), 8);
        assert_eq!(e.maximo_seguro.as_deref(), Some("equilibrado"));
        let max = e.perfiles.iter().find(|p| p.perfil.id == "maximo").unwrap();
        assert!(max.cabe_en_memoria && !max.cabe_en_disco);
    }

    #[test]
    fn sin_analisis_todo_disponible_y_el_mas_ligero_por_defecto() {
        let e = evaluar(&Catalogo::incrustado(), None);
        assert_eq!(e.memoria_para_ia_gb, None);
        assert_eq!(e.maximo_seguro, None);
        assert_eq!(e.recomendado, "minimo");
        assert!(e.perfiles.iter().all(|p| p.cabe()));
    }

    #[test]
    fn la_integrada_no_suma_vram() {
        let mut e = equipo(16, None, 200);
        e.gpus[0].vram_mb = Some(1024);
        assert_eq!(memoria_para_ia_gb(&Catalogo::incrustado().reglas, &e), 11.0);
    }

    #[test]
    fn serializa_en_camel_case_para_el_asistente() {
        let json = serde_json::to_value(ev(16, None, 200)).unwrap();
        assert_eq!(json["recomendado"], "equilibrado");
        assert_eq!(json["maximoSeguro"], "maximo");
        assert_eq!(json["perfiles"][0]["id"], "minimo");
        assert_eq!(json["perfiles"][0]["cabeEnMemoria"], true);
        assert!(json["perfiles"][0]["resultado"].as_str().unwrap().len() > 10);
        assert_eq!(json["perfiles"][4]["experimental"], true);
    }
}
