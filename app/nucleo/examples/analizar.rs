//! `cargo run -p tarkor-nucleo --example analizar`: muestra lo que detectaría el asistente en
//! este equipo y los perfiles resultantes. Útil para probar la detección en la Steam Deck.
use tarkor_nucleo::{config::Rutas, equipo, perfiles};

fn main() {
    let rutas = Rutas::del_sistema();
    let e = equipo::analizar(&rutas.datos);
    println!("{}", serde_json::to_string_pretty(&e).unwrap());
    println!("{}", serde_json::to_string_pretty(&perfiles::evaluar(Some(&e))).unwrap());
}
