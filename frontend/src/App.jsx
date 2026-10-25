import { useState, useEffect, useCallback, useMemo } from 'react'
import './App.css'
import './MediaGrid.css'
import { getHealth, searchFiles } from './api'
import Lightbox from './Lightbox'
import People from './People'
import { tileBadgeLabel } from './mediaLabels'

const PAGE_SIZE = 50
// Derived from the page's own hostname rather than hardcoded, so this
// works whether the app is opened as http://localhost:5173 (API on
// localhost:8000) or from another device on the network, e.g.
// http://192.168.1.50:5173 (API on 192.168.1.50:8000). A hardcoded
// 'localhost' here would resolve to the *viewing device* — the phone
// itself, not the Mac Mini — breaking every API call while the page
// still loads fine.
const API_BASE = `http://${window.location.hostname}:8000`

const UNKNOWN_GROUP = 'Unknown date'

function monthYearLabel(dateTaken) {
  if (!dateTaken) return UNKNOWN_GROUP
  const d = new Date(dateTaken)
  if (isNaN(d.getTime())) return UNKNOWN_GROUP
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

/**
 * Sort files newest-to-oldest by date_taken (undated files last), then
 * group them into { label, files[] } buckets by month/year. Returns a
 * flat sorted list alongside the groups so the lightbox can navigate
 * in the same order the groups are displayed. The API already returns
 * results in this same newest-first order, so this is mostly about
 * producing the month/year section headers rather than re-sorting.
 */
function groupByMonth(files) {
  const sorted = [...files].sort((a, b) => {
    const da = a.date_taken ? new Date(a.date_taken).getTime() : -Infinity
    const db = b.date_taken ? new Date(b.date_taken).getTime() : -Infinity
    return db - da
  })

  const groups = []
  let currentLabel = null
  let currentGroup = null

  for (const file of sorted) {
    const label = monthYearLabel(file.date_taken)
    if (label !== currentLabel) {
      currentGroup = { label, files: [] }
      groups.push(currentGroup)
      currentLabel = label
    }
    currentGroup.files.push(file)
  }

  return { sorted, groups }
}

// Sub-filter option lists for the video facets. `key` is what gets sent
// to the API (must match the bucket keys in database.py's
// _LENGTH_CATEGORY_RANGES / _RESOLUTION_TIER_RANGES exactly); `label` is
// the display text. Deliberately kept in the same order/wording as
// resolutionTier()/lengthCategory() above so a tag on a video result
// ("1080p · Short clip") reads identically to the matching filter button.
const VIDEO_RESOLUTION_OPTIONS = [
  { key: '4k', label: '4K' },
  { key: '1080p', label: '1080p' },
  { key: '720p', label: '720p' },
  { key: 'sd', label: 'SD' },
]

const VIDEO_LENGTH_OPTIONS = [
  { key: 'live_photo', label: 'Live Photo' },
  { key: 'short_clip', label: 'Short clip' },
  { key: 'clip', label: 'Video' },
  { key: 'long_video', label: 'Long video' },
]

export default function App() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  const [queryInput, setQueryInput] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [mediaFilter, setMediaFilter] = useState('all')

  // Video sub-filters — only meaningful (and only shown) while
  // mediaFilter === 'video'. Each is a multi-select array of option
  // keys; values within one facet are OR'd, the two facets are AND'd
  // together server-side (see _build_video_filter_clause in database.py).
  const [videoResolutions, setVideoResolutions] = useState([])
  const [videoLengths, setVideoLengths] = useState([])

  // Explicit date range filter (from a date-picker UI) — independent
  // of the free-text query's own year/month/season parsing, and
  // persists across every other filter change (media type, video
  // sub-filters, clearing the search text) until explicitly cleared,
  // same as videoResolutions/videoLengths already do relative to a
  // media-type switch back to 'all'/'image'.
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [results, setResults] = useState([])
  const [resultOffset, setResultOffset] = useState(0)
  const [resultTotal, setResultTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const [lightboxIndex, setLightboxIndex] = useState(null)

  // Top-level tab: 'library' is the existing search/gallery experience;
  // 'people' is the People page (grid of clustered faces -> per-person
  // photo view). Kept as a simple string flag rather than a router,
  // since this is a small local app with no need for deep-linkable URLs.
  const [view, setView] = useState('library')

  // The single query function behind every view — an empty query with
  // no media filter returns the entire library, newest first, which is
  // exactly what powers the initial "everything" gallery below as well
  // as any typed search. There's no separate "browse mode" anymore.
  //
  // Takes a single bundled filters object rather than positional args —
  // this grew past the point where positional args stayed readable once
  // the video sub-filters were added. `append` stays a separate second
  // argument since it's a call-site behavior flag, not a filter value.
  const runQuery = useCallback(async (filters, append = false) => {
    const {
      query, mediaFilter: mFilter, offset: off,
      videoResolutions: vRes, videoLengths: vLen,
      dateFrom: dFrom, dateTo: dTo,
    } = filters
    setLoading(true)
    setError(null)
    try {
      const params = { limit: PAGE_SIZE, offset: off }
      if (mFilter === 'image') params.media_type = 'image'
      if (mFilter === 'video') params.media_type = 'video'
      // Sub-filters only ever apply while browsing video — guarded here
      // too (not just by the UI being hidden otherwise) so a stale call
      // can't accidentally send them while mFilter isn't 'video'.
      if (mFilter === 'video' && vRes && vRes.length) params.video_resolution = vRes.join(',')
      if (mFilter === 'video' && vLen && vLen.length) params.video_length = vLen.join(',')
      if (dFrom) params.date_from = dFrom
      if (dTo) params.date_to = dTo
      const r = await searchFiles(query, params)
      setResults(prev => append ? [...prev, ...r.data.files] : r.data.files)
      setResultTotal(r.data.total)
    } catch {
      setError('Failed to load photos.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    getHealth().then(r => setHealth(r.data)).catch(() => setError('API not reachable — is the server running?'))
    runQuery({ query: '', mediaFilter: 'all', offset: 0, videoResolutions: [], videoLengths: [], dateFrom: '', dateTo: '' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    const query = queryInput.trim()
    setActiveQuery(query)
    setResultOffset(0)
    setResults([])
    runQuery({ query, mediaFilter, offset: 0, videoResolutions, videoLengths, dateFrom, dateTo })
  }

  const changeMediaFilter = (f) => {
    setMediaFilter(f)
    setResultOffset(0)
    setResults([])
    // Leaving Video clears both sub-filter arrays so they don't silently
    // linger and reapply unexpectedly if Video is reselected later.
    const nextVideoResolutions = f === 'video' ? videoResolutions : []
    const nextVideoLengths = f === 'video' ? videoLengths : []
    if (f !== 'video') {
      setVideoResolutions([])
      setVideoLengths([])
    }
    runQuery({ query: activeQuery, mediaFilter: f, offset: 0, videoResolutions: nextVideoResolutions, videoLengths: nextVideoLengths, dateFrom, dateTo })
  }

  const toggleVideoResolution = (key) => {
    const next = videoResolutions.includes(key)
      ? videoResolutions.filter(k => k !== key)
      : [...videoResolutions, key]
    setVideoResolutions(next)
    setResultOffset(0)
    setResults([])
    runQuery({ query: activeQuery, mediaFilter, offset: 0, videoResolutions: next, videoLengths, dateFrom, dateTo })
  }

  const toggleVideoLength = (key) => {
    const next = videoLengths.includes(key)
      ? videoLengths.filter(k => k !== key)
      : [...videoLengths, key]
    setVideoLengths(next)
    setResultOffset(0)
    setResults([])
    runQuery({ query: activeQuery, mediaFilter, offset: 0, videoResolutions, videoLengths: next, dateFrom, dateTo })
  }

  const applyDateFrom = (value) => {
    setDateFrom(value)
    setResultOffset(0)
    setResults([])
    runQuery({ query: activeQuery, mediaFilter, offset: 0, videoResolutions, videoLengths, dateFrom: value, dateTo })
  }

  const applyDateTo = (value) => {
    setDateTo(value)
    setResultOffset(0)
    setResults([])
    runQuery({ query: activeQuery, mediaFilter, offset: 0, videoResolutions, videoLengths, dateFrom, dateTo: value })
  }

  const clearDateRange = () => {
    setDateFrom('')
    setDateTo('')
    setResultOffset(0)
    setResults([])
    runQuery({ query: activeQuery, mediaFilter, offset: 0, videoResolutions, videoLengths, dateFrom: '', dateTo: '' })
  }

  const loadMore = () => {
    const next = resultOffset + PAGE_SIZE
    setResultOffset(next)
    runQuery({ query: activeQuery, mediaFilter, offset: next, videoResolutions, videoLengths, dateFrom, dateTo }, true)
  }

  const clearSearch = () => {
    setQueryInput('')
    setActiveQuery('')
    setResultOffset(0)
    setResults([])
    runQuery({ query: '', mediaFilter, offset: 0, videoResolutions, videoLengths, dateFrom, dateTo })
  }

  const { sorted: sortedResults, groups: groupedResults } = useMemo(
    () => groupByMonth(results),
    [results]
  )

  return (
    <div className="app">
      <div className="header">
        <h1>FamilyVault</h1>
        <p>Private photo and video library</p>
      </div>

      {error && <div className="error">{error}</div>}

      <form className="search-bar" onSubmit={handleSearchSubmit}>
        <input
          type="text"
          className="search-input"
          placeholder="Search anything: keywords, places, month, season, year... e.g. birthday, Paris, summer 2019"
          value={queryInput}
          onChange={e => setQueryInput(e.target.value)}
        />
        <button type="submit" className="search-btn">
          Search
        </button>
        {activeQuery && (
          <button type="button" className="search-clear" onClick={clearSearch}>
            Clear
          </button>
        )}
      </form>

      <div className="view-tabs">
        <button className={`view-tab ${view === 'library' ? 'active' : ''}`} onClick={() => setView('library')}>
          Library
        </button>
        <button className={`view-tab ${view === 'people' ? 'active' : ''}`} onClick={() => setView('people')}>
          People
        </button>
      </div>

      {view === 'library' && (
        <>
          <div className="status-bar">
            <div className="stat-card">
              <div className="label">Status</div>
              <div className={`value ${health ? 'green' : ''}`}>{health ? 'Online' : '—'}</div>
            </div>
            <div className="stat-card">
              <div className="label">Total Files</div>
              <div className="value">{health ? health.total_files.toLocaleString() : '—'}</div>
            </div>
          </div>

          <div className="section-title">
            {activeQuery
              ? `Search results for "${activeQuery}" — ${resultTotal.toLocaleString()} match${resultTotal === 1 ? '' : 'es'}`
              : `All photos & videos — ${resultTotal.toLocaleString()} total`}
          </div>

          <div className="filters">
            {['all', 'image', 'video'].map(f => (
              <button key={f} className={`filter-btn ${mediaFilter === f ? 'active' : ''}`} onClick={() => changeMediaFilter(f)}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          <div className="date-range-filters">
            <label className="date-range-label">
              From
              <input
                type="date"
                className="date-range-input"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={e => applyDateFrom(e.target.value)}
              />
            </label>
            <label className="date-range-label">
              To
              <input
                type="date"
                className="date-range-input"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={e => applyDateTo(e.target.value)}
              />
            </label>
            {(dateFrom || dateTo) && (
              <button type="button" className="date-range-clear" onClick={clearDateRange}>
                Clear dates
              </button>
            )}
          </div>

          {mediaFilter === 'video' && (
            <div className="video-subfilters">
              <div className="subfilter-group">
                <span className="subfilter-label">Resolution</span>
                {VIDEO_RESOLUTION_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    className={`subfilter-btn ${videoResolutions.includes(opt.key) ? 'active' : ''}`}
                    onClick={() => toggleVideoResolution(opt.key)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <div className="subfilter-group">
                <span className="subfilter-label">Length</span>
                {VIDEO_LENGTH_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    className={`subfilter-btn ${videoLengths.includes(opt.key) ? 'active' : ''}`}
                    onClick={() => toggleVideoLength(opt.key)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {results.length === 0 && !loading && (
            <div className="empty">
              {activeQuery
                ? `No matches for "${activeQuery}". Search covers captions, locations, month, season, and year — most of the library hasn't been captioned yet, and only files with GPS data have a resolved location.`
                : mediaFilter === 'video' && (videoResolutions.length > 0 || videoLengths.length > 0)
                  ? 'No videos match the selected resolution/length filters.'
                  : 'No files yet. Run: familyvault scan <path>'}
            </div>
          )}

          {groupedResults.map((group) => (
            <div key={group.label} className="date-group">
              <div className="date-group-header">{group.label}</div>
              <div className="media-grid">
                {group.files.map((file) => {
                  const lightboxIdx = sortedResults.indexOf(file)

                  return (
                    <div
                      key={file.id}
                      className="media-tile"
                      onClick={() => setLightboxIndex(lightboxIdx)}
                    >
                      <img
                        className="media-tile-thumb"
                        src={`${API_BASE}/files/${file.id}/thumbnail`}
                        alt=""
                        loading="lazy"
                        onError={e => { e.target.style.display = 'none' }}
                      />
                      <span className={`media-tile-badge ${file.is_image ? 'img' : 'vid'}`}>
                        {tileBadgeLabel(file)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          {results.length < resultTotal && (
            <button className="load-more" onClick={loadMore} disabled={loading}>
              {loading ? 'Loading...' : `Load more (${(resultTotal - results.length).toLocaleString()} remaining)`}
            </button>
          )}

          {lightboxIndex !== null && (
            <Lightbox
              files={sortedResults}
              index={lightboxIndex}
              onClose={() => setLightboxIndex(null)}
              onNavigate={setLightboxIndex}
            />
          )}
        </>
      )}

      {view === 'people' && <People />}
    </div>
  )
}
