import { useEffect, useState } from 'react'

function App() {
  const [health, setHealth] = useState<string>('checking...')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => setHealth(data.status === 'ok' ? 'Backend connected' : 'Error'))
      .catch(() => setHealth('Backend not reachable'))
  }, [])

  return (
    <div className="min-h-screen bg-white flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-3xl font-semibold text-gray-900 mb-2">
          Influencer Trigger
        </h1>
        <p className="text-gray-500 text-sm mb-6">
          社交媒体网红自动触发系统
        </p>
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-gray-50 border border-gray-200">
          <span
            className={`w-2 h-2 rounded-full ${
              health === 'Backend connected' ? 'bg-green-400' : 'bg-gray-300'
            }`}
          />
          <span className="text-sm text-gray-600">{health}</span>
        </div>
      </div>
    </div>
  )
}

export default App
