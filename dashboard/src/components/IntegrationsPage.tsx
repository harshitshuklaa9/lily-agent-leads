import { useState, useEffect } from 'react'
import { apiUrl } from '../api'

interface Provider {
  id: string
  name: string
  description: string
  docsUrl: string
  keyLabel: string
  keyPlaceholder: string
}

const PROVIDERS: Provider[] = [
  {
    id: 'linkedin_sales_nav',
    name: 'LinkedIn Sales Navigator',
    description: 'Find verified contacts with email addresses and direct LinkedIn profiles using the official Sales Navigator API.',
    docsUrl: 'https://learn.microsoft.com/en-us/linkedin/sales/getting-started',
    keyLabel: 'Access Token',
    keyPlaceholder: 'AQV...',
  },
  {
    id: 'clay',
    name: 'Clay',
    description: "Enrich contact data with verified emails, phone numbers, and enriched profiles via Clay's people search.",
    docsUrl: 'https://docs.clay.com/api',
    keyLabel: 'API Key',
    keyPlaceholder: 'clay_...',
  },
  {
    id: 'apollo',
    name: 'Apollo.io',
    description: 'Surface decision-makers with verified emails and mobile numbers. Free tier available with 50 credits/month.',
    docsUrl: 'https://apolloio.github.io/apollo-api-docs',
    keyLabel: 'API Key',
    keyPlaceholder: 'your_apollo_api_key',
  },
]

interface Props {
  onClose: () => void
  inline?: boolean
}

export function IntegrationsPage({ onClose, inline = false }: Props) {
  const [connected, setConnected] = useState<Record<string, boolean>>({})
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [messages, setMessages] = useState<Record<string, { text: string; ok: boolean }>>({})

  useEffect(() => {
    fetch(apiUrl('/integrations'))
      .then(r => r.json())
      .then(setConnected)
      .catch(() => {})
  }, [])

  function showMessage(provider: string, text: string, ok: boolean) {
    setMessages(m => ({ ...m, [provider]: { text, ok } }))
    setTimeout(() => setMessages(m => { const n = { ...m }; delete n[provider]; return n }), 3000)
  }

  async function connect(provider: string) {
    const key = keys[provider]?.trim()
    if (!key) return
    setSaving(s => ({ ...s, [provider]: true }))
    try {
      const res = await fetch(apiUrl('/integrations'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: key }),
      })
      if (!res.ok) throw new Error()
      setConnected(c => ({ ...c, [provider]: true }))
      setKeys(k => ({ ...k, [provider]: '' }))
      showMessage(provider, 'Connected! Next pipeline run will use this provider.', true)
    } catch {
      showMessage(provider, 'Failed to save key. Try again.', false)
    } finally {
      setSaving(s => ({ ...s, [provider]: false }))
    }
  }

  async function disconnect(provider: string) {
    setSaving(s => ({ ...s, [provider]: true }))
    try {
      await fetch(apiUrl(`/integrations/${provider}`), { method: 'DELETE' })
      setConnected(c => ({ ...c, [provider]: false }))
      showMessage(provider, 'Disconnected.', true)
    } catch {
      showMessage(provider, 'Failed to disconnect.', false)
    } finally {
      setSaving(s => ({ ...s, [provider]: false }))
    }
  }

  const inner = (
    <>
      {/* Header */}
      {!inline && (
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Integrations</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Connect an API to replace the default LinkedIn scraper with verified contact data.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>
      )}

      {/* Provider cards */}
      <div className={inline ? 'space-y-4' : 'px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto'}>
          {PROVIDERS.map(p => {
            const isConnected = connected[p.id]
            const isSaving = saving[p.id]
            const msg = messages[p.id]

            return (
              <div
                key={p.id}
                className={`border rounded-xl p-4 transition-colors ${
                  isConnected ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-white'
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-semibold text-gray-900 text-sm">{p.name}</span>
                      {isConnected && (
                        <span className="flex items-center gap-1 text-xs text-green-600 font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
                          Connected
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mb-3">{p.description}</p>

                    {!isConnected && (
                      <div className="flex gap-2">
                        <input
                          type="password"
                          placeholder={p.keyPlaceholder}
                          value={keys[p.id] ?? ''}
                          onChange={e => setKeys(k => ({ ...k, [p.id]: e.target.value }))}
                          onKeyDown={e => e.key === 'Enter' && connect(p.id)}
                          className="flex-1 text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                        <button
                          onClick={() => connect(p.id)}
                          disabled={isSaving || !keys[p.id]?.trim()}
                          className="text-xs bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap"
                        >
                          {isSaving ? 'Saving...' : 'Connect'}
                        </button>
                      </div>
                    )}

                    {isConnected && (
                      <button
                        onClick={() => disconnect(p.id)}
                        disabled={isSaving}
                        className="text-xs text-red-500 hover:text-red-700 font-medium"
                      >
                        {isSaving ? 'Disconnecting...' : 'Disconnect'}
                      </button>
                    )}

                    {msg && (
                      <p className={`text-xs mt-2 ${msg.ok ? 'text-green-600' : 'text-red-500'}`}>
                        {msg.text}
                      </p>
                    )}
                  </div>

                  <a
                    href={p.docsUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-500 hover:underline whitespace-nowrap"
                  >
                    Docs →
                  </a>
                </div>
              </div>
            )
          })}
        </div>

      {/* Footer */}
      <div className={inline ? 'mt-6 pt-4 border-t border-gray-100' : 'px-6 py-4 border-t border-gray-100 bg-gray-50'}>
        <p className="text-xs text-gray-400">
          API keys are stored securely in your database. The pipeline uses the first connected provider
          and falls back to LinkedIn search if none are configured.
        </p>
      </div>
    </>
  )

  if (inline) return <>{inner}</>

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {inner}
      </div>
    </div>
  )
}
