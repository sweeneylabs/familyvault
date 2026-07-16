import axios from 'axios'

// Uses whatever host the browser loaded the page from (localhost for you,
// or your Mac's LAN IP for family members on the same network), so this
// doesn't need to be updated if your IP changes.
const API_HOST = window.location.hostname

const api = axios.create({
  baseURL: `http://${API_HOST}:8000`,
  timeout: 10000,
})

export const getHealth = () => api.get('/health')
export const getScans = () => api.get('/scans')
export const getScan = (id) => api.get(`/scans/${id}`)
export const getScanFiles = (id, params = {}) => api.get(`/scans/${id}/files`, { params })
export const searchFiles = (query, params = {}) => api.get('/search', { params: { q: query, ...params } })
