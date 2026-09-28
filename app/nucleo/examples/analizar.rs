//! `cargo run -p tarkor-nucleo --example analizar`: muestra lo que detectaría el asistente en
//! este equipo y los perfiles resultantes. Útil para probar la detección en la Steam Deck.
use tarkor_nucleo::{catalogo::Catalogo, config::Rutas, equipo, perfiles, rendimiento};

fn main() {
    let rutas = Rutas::del_sistema();
    let e = equipo::analizar(&rutas.datos);
    println!("{}", serde_json::to_string_pretty(&e).unwrap());
    let (catalogo, origen) = Catalogo::cargar(&rutas.datos);
    let ev = perfiles::evaluar(&catalogo, Some(&e));
    println!("catálogo: {origen:?}");
    println!("{}", serde_json::to_string_pretty(&ev).unwrap());
    let recomendado = catalogo.perfil(&ev.recomendado).unwrap();
    let ajustes = rendimiento::calcular(&catalogo, recomendado, Some(&e), perfiles::UsoCpu::Moderado);
    println!("{}", serde_json::to_string_pretty(&ajustes).unwrap());
}
