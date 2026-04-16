import { IntegrationsPage } from './IntegrationsPage'

export function AdminPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-8 py-5">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Lily Agent — Admin</h1>
            <p className="text-sm text-gray-400 mt-0.5">Integration settings · Not visible to sales reps</p>
          </div>
          <a
            href="/"
            className="text-sm text-blue-600 hover:underline"
          >
            ← Back to dashboard
          </a>
        </div>
      </div>

      {/* Integrations inline (not modal) */}
      <div className="max-w-2xl mx-auto w-full px-8 py-10">
        <IntegrationsPage onClose={() => window.location.href = '/'} inline />
      </div>
    </div>
  )
}
