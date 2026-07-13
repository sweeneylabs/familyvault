import { useState, useEffect, useCallback } from 'react'
import './App.css'
import { getHealth, getScans, getScanFiles } from './api'

const PAGE_SIZE = 50

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + ' MB'
  return (bytes / 1024 ** 3).toFixed(2) + ' GB'
}

function formatDate(iso) {
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [scans, setScans] = useState([])
  const [selectedScan, setSelectedScan] = useState(null)
  const [files, setFiles] = useState([])
  const [filter, setFilter] = useState('all')
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getHealth().then(r => setHealth(r.data)).catch(() => setError('API not reachable — is the server running?'))
    getScans().then(r => setScans(r.data.scans)).catch(() => {})
  }, [])

  const loadFiles = useCallback(async (scan, f, off, append = false) => {
    if (!scan) return
    setLoading(true)
    try {
      const params = { limit: PAGE_SIZE, offset: off }
      if (f === 'image') params.media_type = 'image'
      if (f === 'video') params.media_type = 'video'
      const r = await getScanFiles(scan.id, params)
      setFiles(prev => append ? [...prev, ...r.data.files] : r.data.files)
      setTotal(r.data.total)
    } catch {
      setError('Failed to load files.')
    } finally {
      setLoading(false)
    }
  }, [])

  const selectScan = (scan) => {
    setSelectedScan(scan)
    setFilter('all')
    setOffset(0)
    setFiles([])
    loadFiles(scan, 'all', 0)
  }

  const changeFilter = (f) => {
    setFilter(f)
    setOffset(0)
    setFiles([])
    loadFiles(selectedScan, f, 0)
  }

  const loadMore = () => {
    const next = offset + PAGE_SIZE
    setOffset(next)
    loadFiles(selectedScan, filter, next, true)
  }

  return (
    <div className="app">
      <div className="header">
        <h1>FamilyVault</h1>
        <p>Private photo and video library</p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="status-bar">
        <div className="stat-card">
          <div className="label">Status</div>
          <div className={`value ${health ? 'green' : ''}`}>{health ? 'Online' : '—'}</div>
        </div>
        <div className="stat-card">
          <div className="label">Total Files</div>
          <div className="value">{health ? health.total_files.toLocaleString() : '—'}</div>
        </div>
        <div className="stat-card">
          <div className="label">Scans</div>
          <div className="value">{scans.length}</div>
        </div>
      </div>

      <div className="section-title">Scan History</div>
      <div className="scan-list">
        {scans.length === 0 && <div className="empty">No scans yet. Run: familyvault scan &lt;path&gt;</div>}
        {scans.map(scan => (
          <div
            key={scan.id}
            className={`scan-card ${selectedScan?.id === scan.id ? 'active' : ''}`}
            onClick={() => selectScan(scan)}
          >
            <div className="scan-info">
              <div className="scan-root">{scan.root_path}</div>
              <div className="scan-meta">{formatDate(scan.scanned_at)} · {formatBytes(scan.total_size_bytes)}</div>
            </div>
            <div className="scan-counts">
              <div className="count">{scan.total_count.toLocaleString()}</div>
              <div className="count-label">files</div>
            </div>
          </div>
        ))}
      </div>

      {selectedScan && (
        <>
          <div className="section-title">Files — Scan #{selectedScan.id}</div>
          <div className="filters">
            {['all', 'image', 'video'].map(f => (
              <button key={f} className={`filter-btn ${filter === f ? 'active' : ''}`} onClick={() => changeFilter(f)}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
            <span style={{ color: '#475569', fontSize: '0.8rem', alignSelf: 'center', marginLeft: '0.5rem' }}>
              {total.toLocaleString()} files
            </span>
          </div>
          <div className="file-grid">
            {files.map((file, i) => (
              <div key={i} className="file-row">
                <span className={`badge ${file.is_image ? 'img' : 'vid'}`}>
                  {file.is_image ? 'IMG' : 'VID'}
                </span>
                <span className="file-path">{file.path}</span>
                <span className="file-size">{formatBytes(file.size_bytes)}</span>
              </div>
            ))}
          </div>
          {files.length < total && (
            <button className="load-more" onClick={loadMore} disabled={loading}>
              {loading ? 'Loading...' : `Load more (${(total - files.length).toLocaleString()} remaining)`}
            </button>
          )}
        </>
      )}
    </div>
  )
}