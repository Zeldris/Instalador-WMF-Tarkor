// Licencias y avisos (docs/08, sección 2; docs/11): «Built with Llama», el aviso de Llama 3.1, el enlace a su
// política de uso y el texto completo de cada licencia. Se abre desde el paso 2 y desde Ajustes.

import { useEffect, useState } from 'react'
import { api } from './api'
import { Pagina } from './componentes'
import type { Catalogo, GrupoLicencias, LicenciasTerceros, Perfil } from './tipos'
import * as tx from './textos'
import apache from './licencias/Apache-2.0.txt?raw'
import llama from './licencias/Llama-3.1-Community.txt?raw'
import ollama from './licencias/ollama-MIT.txt?raw'

// Las licencias de terceros las genera el build (INS-47) y no se versionan: con `glob` el archivo es opcional y
// `tsc`, vitest y `npm run dev` funcionan sin generarlo. Sin `eager`, el JSON (cientos de KB) va a su propio
// fragmento y solo se baja al montar la sección; el build de producción exige que exista (vite.config.ts).
const generadas = import.meta.glob<LicenciasTerceros>('./licencias/generadas/terceros.json', { import: 'default' })

/** Carga perezosa de `terceros.json`; null si no se generó. */
export async function cargarTerceros(): Promise<LicenciasTerceros | null> {
  const cargar = Object.values(generadas)[0]
  if (!cargar) return null
  try { return await cargar() } catch { return null }
}

/** Id de la licencia de Llama en el catálogo (pide «Built with Llama» y su aviso). */
export const LICENCIA_LLAMA = 'Llama-3.1-Community'

/** Texto completo de cada licencia que aparece en el catálogo o en el motor. Una licencia nueva sin texto aquí no pasa los tests. */
export const textosLicencia: Record<string, string> = {
  [LICENCIA_LLAMA]: llama,
  'Apache-2.0': apache,
  MIT: ollama,
}

/** Modelos del catálogo agrupados por licencia, en el orden en que aparecen. */
export function modelosPorLicencia(catalogo: Catalogo): [string, string[]][] {
  const grupos = new Map<string, string[]>()
  for (const [modelo, m] of Object.entries(catalogo.modelos)) grupos.set(m.licencia, [...(grupos.get(m.licencia) ?? []), modelo])
  return [...grupos]
}

/** Si alguno de los modelos del perfil tiene esa licencia. */
function perfilConLicencia(catalogo: Catalogo, p: Perfil, licencia: string): boolean {
  return [p.narrador, p.cronista, p.sugerencias, p.embeddings].some((m) => catalogo.modelos[m]?.licencia === licencia)
}

function TextoCompleto({ licencia }: { licencia: string }) {
  const t = tx.licencias
  return (
    <details>
      <summary>{t.textoCompleto(t.nombres[licencia] ?? licencia)}</summary>
      <pre className="licencia">{textosLicencia[licencia]}</pre>
    </details>
  )
}

function GrupoTerceros({ grupo }: { grupo: GrupoLicencias }) {
  const t = tx.licencias
  // El contenido (hasta cientos de textos) solo se pinta al abrir el grupo.
  const [abierto, setAbierto] = useState(false)
  return (
    <details className="grupo-licencia" onToggle={(e) => setAbierto(e.currentTarget.open)}>
      <summary><b>{grupo.licencia}</b> · <span>{t.tercerosResumen(grupo.paquetes.length)}</span></summary>
      {abierto && <>
        <ul className="peq">
          {grupo.paquetes.map((p) => <li key={`${p.ecosistema}/${p.nombre}@${p.version}`}><span className="mono">{p.nombre} {p.version}</span> <span className="tenue">({t.tercerosEcosistema[p.ecosistema] ?? p.ecosistema})</span></li>)}
        </ul>
        {grupo.textos.map((x, i) => (
          <div key={i}>
            <p className="peq tenue">{t.tercerosUsadoPor(x.paquetes.length)}: {x.paquetes.map((n) => grupo.paquetes[n].nombre).join(', ')}</p>
            <pre className="licencia">{x.texto}</pre>
          </div>
        ))}
      </>}
    </details>
  )
}

/** «Licencias de terceros», como chrome://credits: un grupo desplegable por licencia. Sin datos, una línea discreta. */
export function LicenciasDeTerceros({ datos: dados, cargar = cargarTerceros }: { datos?: LicenciasTerceros | null; cargar?: () => Promise<LicenciasTerceros | null> }) {
  const t = tx.licencias
  // `undefined` = todavía cargando (no se pinta nada bajo el título); `null` = no se generó.
  const [cargados, setCargados] = useState<LicenciasTerceros | null | undefined>(dados)
  useEffect(() => {
    if (dados !== undefined) return
    let vivo = true
    cargar().then((d) => { if (vivo) setCargados(d) }, () => { if (vivo) setCargados(null) })
    return () => { vivo = false }
  }, [dados, cargar])
  const datos = dados !== undefined ? dados : cargados
  return (
    <div className="caja">
      <h2>{t.terceros}</h2>
      {datos === undefined ? null : datos && datos.grupos.length > 0
        ? <>
          <p className="peq">{t.tercerosLead}</p>
          {datos.grupos.map((g) => <GrupoTerceros key={g.licencia} grupo={g} />)}
        </>
        : <p className="peq tenue">{t.tercerosSin}</p>}
    </div>
  )
}

function CopiarEnlace({ url }: { url: string }) {
  const t = tx.licencias
  const [estado, setEstado] = useState<'copiado' | 'error' | null>(null)
  const copiar = async () => {
    try {
      await api.copiar(url)
      setEstado('copiado')
    } catch {
      setEstado('error')
    }
  }
  return (
    <>
      <p className="peq">{t.politica} <span className="ruta">{url}</span></p>
      <div className="fila">
        <button type="button" className="btn" onClick={() => void copiar()}>{t.copiarEnlace}</button>
        {estado === 'copiado' && <span className="peq tenue" role="status">{t.copiado}</span>}
      </div>
      {estado === 'error' && <div className="error" role="alert">{t.errorCopiar}</div>}
    </>
  )
}

export function Licencias({ volver, cargarTerceros: cargar }: { volver: () => void; cargarTerceros?: () => Promise<LicenciasTerceros | null> }) {
  const t = tx.licencias
  // El catálogo que cargó el núcleo (puede ser el externo), no el incrustado; mientras llega se pinta el resto.
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null)
  useEffect(() => {
    let vivo = true
    api.catalogo().then((c) => { if (vivo) setCatalogo(c) }, () => {})
    return () => { vivo = false }
  }, [])
  const grupos = catalogo ? modelosPorLicencia(catalogo) : []
  const conLlama = catalogo ? catalogo.perfiles.filter((p) => perfilConLicencia(catalogo, p, LICENCIA_LLAMA)).map((p) => p.nombre) : []
  const hayLlama = grupos.some(([l]) => l === LICENCIA_LLAMA)
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.lead}
        barra={<><button type="button" className="btn" onClick={volver}>{t.volver}</button><span className="hueco" /></>}>
        {hayLlama && (
          <div className="caja">
            <h2>{t.builtWithLlama}</h2>
            <p className="peq">{t.builtWithLlamaLead(conLlama)}</p>
          </div>
        )}
        <div className="caja">
          <h2>{t.motor}</h2>
          <p className="peq"><b>{t.motorNombre}</b> · {t.nombres.MIT}</p>
          <TextoCompleto licencia="MIT" />
        </div>
        <div className="caja">
          <h2>{t.modelos}</h2>
          {grupos.map(([licencia, modelos]) => (
            <div key={licencia} className="grupo-licencia">
              <p className="peq"><b>{t.nombres[licencia] ?? licencia}</b>: <span className="mono">{modelos.join(', ')}</span></p>
              {licencia === LICENCIA_LLAMA && <>
                <p className="peq">{t.avisoLlama}</p>
                <CopiarEnlace url={t.politicaUrl} />
              </>}
              <TextoCompleto licencia={licencia} />
            </div>
          ))}
        </div>
        <p className="peq tenue">{t.fuentes}</p>
        <LicenciasDeTerceros cargar={cargar} />
      </Pagina>
    </div>
  )
}
