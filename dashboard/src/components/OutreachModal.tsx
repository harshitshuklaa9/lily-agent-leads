import { useState, useRef } from 'react'
import type { Contact } from '../types'
import type { GroupedLead } from '../hooks/useLeads'
import { apiUrl } from '../api'

interface Props {
  lead: GroupedLead
  contact: Contact
  onClose: () => void
}

export function OutreachModal({ lead, contact, onClose }: Props) {
  const [subject, setSubject] = useState<string>(contact.outreach_subject ?? '')
  const [body, setBody]       = useState<string>(contact.outreach_body ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [saved, setSaved]     = useState(false)
  const [showSendOptions, setShowSendOptions] = useState(false)
  const [copied, setCopied]   = useState(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const hasEmail = subject && body

  async function generate() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/contacts/${contact.id}/outreach`), { method: 'POST' })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setSubject(data.subject)
      setBody(data.body)
    } catch (e: any) {
      setError(e.message ?? 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  function handleSubjectChange(val: string) {
    setSubject(val)
    scheduleAutoSave(val, body)
  }

  function handleBodyChange(val: string) {
    setBody(val)
    scheduleAutoSave(subject, val)
  }

  function scheduleAutoSave(s: string, b: string) {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setSaved(false)
    saveTimer.current = setTimeout(() => autoSave(s, b), 1200)
  }

  async function autoSave(s: string, b: string) {
    if (!s || !b) return
    try {
      await fetch(apiUrl(`/contacts/${contact.id}/outreach`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: s, body: b }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      // silent — non-blocking
    }
  }

  function copy() {
    if (!subject || !body) return
    navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
    setShowSendOptions(false)
  }

  function openGmail() {
    const gmailUrl = `https://mail.google.com/mail/?view=cm&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    window.open(gmailUrl, '_blank')
    setShowSendOptions(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-6 pb-4 border-b border-gray-100">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">
              {contact.buyer_type === 'technical' ? 'Technical Buyer' : 'Business Buyer'}
            </p>
            <h2 className="text-lg font-semibold text-gray-900">{contact.name ?? 'Unknown'}</h2>
            <p className="text-sm text-gray-500">{contact.title} · {lead.company}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none mt-1">✕</button>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {hasEmail ? (
            <>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Outreach Email</p>
                {saved && <span className="text-xs text-green-500">Saved ✓</span>}
              </div>
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
                {/* Editable subject */}
                <div>
                  <p className="text-xs text-gray-400 mb-1">Subject</p>
                  <input
                    type="text"
                    value={subject}
                    onChange={e => handleSubjectChange(e.target.value)}
                    className="w-full text-sm font-semibold text-gray-900 bg-white border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                {/* Editable body */}
                <div>
                  <p className="text-xs text-gray-400 mb-1">Body</p>
                  <textarea
                    value={body}
                    onChange={e => handleBodyChange(e.target.value)}
                    rows={10}
                    className="w-full text-sm text-gray-700 leading-relaxed bg-white border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  />
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 gap-4">
              <p className="text-sm text-gray-500 text-center">
                No outreach email yet for {contact.name?.split(' ')[0]}.
              </p>
              {error && <p className="text-xs text-red-500">{error}</p>}
              <button
                onClick={generate}
                disabled={loading}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
              >
                {loading ? (
                  <>
                    <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Generating...
                  </>
                ) : 'Generate Outreach Email'}
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 pb-6 pt-2 gap-3">
          {contact.linkedin_url ? (
            <a
              href={contact.linkedin_url}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-blue-600 hover:underline"
            >
              View LinkedIn →
            </a>
          ) : <span />}

          {hasEmail && (
            <div className="relative">
              <button
                onClick={() => setShowSendOptions(v => !v)}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                Send ▾
              </button>

              {showSendOptions && (
                <div className="absolute bottom-full right-0 mb-2 w-56 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden z-10">
                  {/* Copy */}
                  <button
                    onClick={copy}
                    className="w-full text-left px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                  >
                    <span>📋</span>
                    <span>{copied ? 'Copied!' : 'Copy to clipboard'}</span>
                  </button>

                  {/* Gmail */}
                  <button
                    onClick={openGmail}
                    className="w-full text-left px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 border-t border-gray-100"
                  >
                    <span>✉️</span>
                    <span>Open in Gmail</span>
                  </button>

                  {/* CRM options — greyed, link to integrations */}
                  <div className="border-t border-gray-100 px-4 py-2">
                    <p className="text-xs text-gray-400 mb-1.5">CRM integrations</p>
                    {['HubSpot', 'Salesforce', 'Outreach.io'].map(crm => (
                      <div
                        key={crm}
                        className="flex items-center justify-between py-1.5 opacity-50"
                      >
                        <span className="text-sm text-gray-500">{crm}</span>
                        <span className="text-xs text-gray-400">Connect →</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
