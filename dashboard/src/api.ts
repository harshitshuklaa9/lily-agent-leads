// In dev, Vite proxy rewrites /leads → localhost:8000
// In production (Vercel), set VITE_API_URL to your Railway API URL
const BASE = import.meta.env.VITE_API_URL ?? ''

export const apiUrl = (path: string) => `${BASE}${path}`
