import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 10000,
})

export const getHealth = () => api.get('/health')
export const getScans = () => api.get('/scans')
export const getScan = (id) => api.get(`/scans/${id}`)
export const getScanFiles = (id, params = {}) => api.get(`/scans/${id}/files`, { params })
export const searchFiles = (query, params = {}) => api.get('/search', { params: { q: query, ...params } })
