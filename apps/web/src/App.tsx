import { useEffect, useState, type FormEvent } from 'react'

const TENANT_ID = '6c4b7c99-14f3-5c71-8b65-ed50dc9ce43c' // DEMO-001 only

type ReviewItem = {
  id: string
  invoice_id: string
  invoice_line_id: string
  created_at: string
  finding_id: string
  rule_id: string
  currency: string
  excess_amount: string
  status: 'needs_review'
}

type Finding = {
  rule_id: string
  currency: string
  allowed_unit_price: string
  invoice_unit_price: string
  quantity: string
  excess_amount: string
  is_violation: boolean
  document_id: string
  document_version: number
  document_sha256: string
  page: number
  clauses: string[]
  graph_edge_ids: string[]
}

type Investigation = {
  id: string
  status: 'complete' | 'needs_review' | 'abstained'
  created_at: string
  invoice_id: string
  invoice_line_id: string
  finding: Finding | null
}

async function getJson<T>(path: string, token: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (response.status === 401) throw new Error('The demo token was rejected.')
  if (response.status === 503) throw new Error('The local API or PostgreSQL is unavailable.')
  if (!response.ok) throw new Error(`Could not load saved evidence (HTTP ${response.status}).`)
  return response.json() as Promise<T>
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-4)}`
}

export default function App() {
  const [entry, setEntry] = useState('')
  const [token, setToken] = useState('')
  const [items, setItems] = useState<ReviewItem[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [queueLoading, setQueueLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    setQueueLoading(true)
    setError('')
    getJson<{ items: ReviewItem[] }>(
      `/api/v1/review/queue?tenant_id=${TENANT_ID}&limit=10`, token, controller.signal,
    ).then((data) => {
      setItems(data.items)
      setSelectedId(data.items[0]?.id ?? '')
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Queue failed to load.')
    }).finally(() => {
      if (!controller.signal.aborted) setQueueLoading(false)
    })
    return () => controller.abort()
  }, [token])

  useEffect(() => {
    if (!token || !selectedId) {
      setInvestigation(null)
      return
    }
    const controller = new AbortController()
    setDetailLoading(true)
    setInvestigation(null)
    getJson<Investigation>(
      `/api/v1/investigations/${encodeURIComponent(selectedId)}?tenant_id=${TENANT_ID}`,
      token, controller.signal,
    ).then(setInvestigation).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Case failed to load.')
    }).finally(() => {
      if (!controller.signal.aborted) setDetailLoading(false)
    })
    return () => controller.abort()
  }, [token, selectedId])

  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!entry.trim()) return
    setItems([])
    setSelectedId('')
    setInvestigation(null)
    setToken(entry.trim())
    setEntry('')
  }

  function disconnect() {
    setToken('')
    setEntry('')
    setItems([])
    setSelectedId('')
    setInvestigation(null)
    setError('')
  }

  const finding = investigation?.finding
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="brandmark">P</span><span>ProcureGraph <em>AI</em></span></div>
        <span className="environment">SYNTHETIC DEMO · READ ONLY</span>
      </header>

      <main>
        <section className="intro">
          <p className="eyebrow">INVESTIGATIONS / REVIEW</p>
          <h1>Price findings, with a trail to the source.</h1>
          <p>Inspect the saved invoice rule, contract clauses and graph relationships before any human decision.</p>
        </section>

        {!token ? (
          <section className="connect card" aria-labelledby="connect-title">
            <h2 id="connect-title">Connect to the local demo</h2>
            <p>Enter the token printed by the local review server. It stays in this tab’s memory and clears on refresh.</p>
            <form onSubmit={connect}>
              <label htmlFor="token">Demo token</label>
              <div className="connect-row">
                <input id="token" type="password" value={entry} autoComplete="off"
                  onChange={(event) => setEntry(event.target.value)} placeholder="Paste local token" />
                <button type="submit" disabled={!entry.trim()}>Open review queue</button>
              </div>
            </form>
          </section>
        ) : (
          <>
            <div className="toolbar"><span>Tenant · DEMO-001</span><button className="text-button" onClick={disconnect}>Disconnect</button></div>
            {error && <div className="alert" role="alert">{error}</div>}
            <div className="workspace">
              <section className="queue card" aria-labelledby="queue-title">
                <div className="section-head"><h2 id="queue-title">Needs review</h2><span>{items.length} shown</span></div>
                {queueLoading && <p role="status">Loading saved findings…</p>}
                {!queueLoading && !error && items.length === 0 && <p className="muted">No saved price findings need review.</p>}
                <div className="queue-list">
                  {items.map((item) => (
                    <button key={item.id} className={`queue-item ${selectedId === item.id ? 'selected' : ''}`}
                      onClick={() => { setError(''); setSelectedId(item.id) }} aria-pressed={selectedId === item.id}>
                      <span className="queue-label">Invoice · {shortId(item.invoice_id)}</span>
                      <strong>{item.currency} {item.excess_amount} excess</strong>
                      <small>{item.rule_id.replaceAll('_', ' ').toLowerCase()}</small>
                    </button>
                  ))}
                </div>
              </section>

              <section className="detail card" aria-labelledby="detail-title">
                <div className="section-head"><h2 id="detail-title">Investigation</h2>{finding && <span className="badge">Needs review</span>}</div>
                {detailLoading && <p role="status">Loading source references…</p>}
                {!detailLoading && !selectedId && <p className="muted">Choose a finding from the review queue.</p>}
                {!detailLoading && finding && (
                  <>
                    <p className="muted">Saved case {shortId(investigation!.id)} · {new Date(investigation!.created_at).toLocaleString('en-IN')}</p>
                    <div className="numbers">
                      <div><span>Contract limit</span><strong>{finding.currency} {finding.allowed_unit_price}</strong><small>per unit, including tolerance</small></div>
                      <div><span>Invoice price</span><strong>{finding.currency} {finding.invoice_unit_price}</strong><small>per unit · quantity {finding.quantity}</small></div>
                      <div className="excess"><span>Calculated excess</span><strong>{finding.currency} {finding.excess_amount}</strong><small>deterministic price rule</small></div>
                    </div>
                    <p className="explanation">Invoice unit price exceeds the allowed contract limit. The excess is the price difference per unit multiplied by quantity. This is a flag for review, not an approved decision.</p>
                    <div className="sources">
                      <div className="source-panel"><h3>Contract document</h3>
                        <dl><dt>Document</dt><dd title={finding.document_id}>{shortId(finding.document_id)} · version {finding.document_version}</dd>
                          <dt>Page and clauses</dt><dd>Page {finding.page} · {finding.clauses.join(', ')}</dd>
                          <dt>SHA-256</dt><dd className="hash">{finding.document_sha256}</dd></dl>
                      </div>
                      <div className="source-panel"><h3>Graph provenance</h3><p>Four source-linked relationships support this invoice chain.</p>
                        <ol>{finding.graph_edge_ids.map((id) => <li key={id} title={id}>{shortId(id)}</li>)}</ol>
                      </div>
                    </div>
                  </>
                )}
              </section>
            </div>
          </>
        )}
      </main>
      <footer>Local synthetic data only · No approvals or ERP actions</footer>
    </div>
  )
}
