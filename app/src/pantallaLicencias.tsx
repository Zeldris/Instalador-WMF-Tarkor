// Licencias y avisos (docs/08, sección 2; docs/11): «Built with Llama», el aviso de Llama 3.1, el enlace a su
// política de uso y el texto completo de cada licencia. Se abre desde el paso 2 y desde Ajustes.

import { useState } from 'react'
import { api } from './api'
import { catalogo } from './catalogo'
import { Pagina } from './componentes'
import * as tx from './textos'
import apache from './licencias/Apache-2.0.txt?raw'
import llama from './licencias/Llama-3.1-Community.txt?raw'
import ollama from './licencias/ollama-MIT.txt?raw'

/** Texto completo de cada licencia que aparece en el catálogo o en el motor. Una licencia nueva sin texto aquí no pasa los tests. */
export const textosLicencia: Record<string, string> = {
  'Llama-3.1-Community': llama,
  'Apache-2.0': apache,
  MIT: ollama,
}

/** Modelos del catálogo agrupados por licencia, en el orden en que aparecen. */
export function modelosPorLicencia(): [string, string[]][] {
  const grupos = new Map<string, string[]>()
  for (const [modelo, m] of Object.entries(catalogo.modelos)) grupos.set(m.licencia, [...(grupos.get(m.licencia) ?? []), modelo])
  return [...grupos]
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

export function Licencias({ volver }: { volver: () => void }) {
  const t = tx.licencias
  const grupos = modelosPorLicencia()
  const hayLlama = grupos.some(([l]) => l === 'Llama-3.1-Community')
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.lead}
        barra={<><button type="button" className="btn" onClick={volver}>{t.volver}</button><span className="hueco" /></>}>
        {hayLlama && (
          <div className="caja">
            <h2>{t.builtWithLlama}</h2>
            <p className="peq">{t.builtWithLlamaLead}</p>
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
              {licencia === 'Llama-3.1-Community' && <>
                <p className="peq">{t.avisoLlama}</p>
                <CopiarEnlace url={t.politicaUrl} />
              </>}
              <TextoCompleto licencia={licencia} />
            </div>
          ))}
        </div>
        <p className="peq tenue">{t.fuentes}</p>
      </Pagina>
    </div>
  )
}
