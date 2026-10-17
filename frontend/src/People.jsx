import { useState, useEffect, useCallback } from 'react'
import './People.css'
import Lightbox from './Lightbox'

const API_BASE = `http://${window.location.hostname}:8000`
const PAGE_SIZE = 50

function PersonCover({ person }) {
  const [failed, setFailed] = useState(false)

  if (!person.has_cover || failed) {
    const initial = person.display_name.charAt(0).toUpperCase()
    return <div className="person-cover person-cover-placeholder">{initial}</div>
  }

  return (
    <img
      className="person-cover"
      src={`${API_BASE}/people/${person.id}/cover`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

function monthYearLabel(dateTaken) {
  if (!dateTaken) return 'Unknown date'
  const d = new Date(dateTaken)
  if (isNaN(d.getTime())) return 'Unknown date'
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

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

function PeopleGrid({ onSelectPerson }) {
  const [people, setPeople] = useState([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadPage = useCallback((off, append = false) => {
    setLoading(true)
    fetch(`${API_BASE}/people?limit=${PAGE_SIZE}&offset=${off}`)
      .then(r => {
        if (!r.ok) throw new Error(`API returned ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (!Array.isArray(data.people)) throw new Error('Unexpected response shape')
        setPeople(prev => append ? [...prev, ...data.people] : data.people)
        setTotal(data.total)
        setError(null)
      })
      .catch(() => setError('Could not load people — the /people API endpoint may be missing or not restarted yet.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadPage(0)
  }, [loadPage])

  const loadMore = () => {
    const next = offset + PAGE_SIZE
    setOffset(next)
    loadPage(next, true)
  }

  if (loading && people.length === 0) return <div className="people-loading">Loading people...</div>
  if (error) return <div className="error">{error}</div>

  if (people.length === 0) {
    return (
      <div className="empty">
        No people found yet. Run <code>familyvault cluster-faces</code> from the command line to group detected faces into people.
      </div>
    )
  }

  return (
    <>
      <div className="people-grid">
        {people.map(person => (
          <div key={person.id} className="person-card" onClick={() => onSelectPerson(person.id)}>
            <PersonCover person={person} />
            <div className="person-card-name">{person.display_name}</div>
            <div className="person-card-count">{person.face_count} photo{person.face_count === 1 ? '' : 's'}</div>
          </div>
        ))}
      </div>

      {people.length < total && (
        <button className="load-more" onClick={loadMore} disabled={loading}>
          {loading ? 'Loading...' : `Load more (${(total - people.length).toLocaleString()} remaining)`}
        </button>
      )}
    </>
  )
}

// Lets the person viewing person A's page fold another cluster (person B)
// into A — every face currently tagged as B gets reassigned to A, and B
// is deleted. Two-step flow within one modal: pick a candidate from a
// filterable list, then a confirmation screen before actually calling
// the API, since this is destructive/irreversible (see database.py's
// merge_people()).
function MergeModal({ keeperPerson, onClose, onMerged }) {
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [filter, setFilter] = useState('')

  const [target, setTarget] = useState(null)
  const [merging, setMerging] = useState(false)
  const [mergeError, setMergeError] = useState(null)

  useEffect(() => {
    setLoading(true)
    fetch(`${API_BASE}/people`)
      .then(r => {
        if (!r.ok) throw new Error(`API returned ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (!Array.isArray(data.people)) throw new Error('Unexpected response shape')
        setCandidates(data.people.filter(p => p.id !== keeperPerson.id))
        setLoadError(null)
      })
      .catch(() => setLoadError('Could not load people to merge with.'))
      .finally(() => setLoading(false))
  }, [keeperPerson.id])

  const filtered = candidates.filter(p =>
    p.display_name.toLowerCase().includes(filter.trim().toLowerCase())
  )

  const confirmMerge = async () => {
    if (!target) return
    setMerging(true)
    setMergeError(null)
    try {
      const r = await fetch(`${API_BASE}/people/${keeperPerson.id}/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loser_ids: [target.id] }),
      })
      if (!r.ok) throw new Error(`API returned ${r.status}`)
      const data = await r.json()
      onMerged(target, data.reassigned)
    } catch {
      setMergeError('Merge failed — please try again.')
    } finally {
      setMerging(false)
    }
  }

  return (
    <div className="merge-modal-overlay" onClick={onClose}>
      <div className="merge-modal" onClick={e => e.stopPropagation()}>
        {target ? (
          <div className="merge-confirm">
            <h3>Merge into {keeperPerson.display_name}?</h3>
            <p className="merge-confirm-detail">
              Every photo currently tagged as <strong>{target.display_name}</strong>{' '}
              ({target.face_count} face{target.face_count === 1 ? '' : 's'}) will be
              reassigned to <strong>{keeperPerson.display_name}</strong>. This can't be undone.
            </p>
            {mergeError && <div className="merge-error">{mergeError}</div>}
            <div className="merge-confirm-actions">
              <button className="merge-btn-confirm" onClick={confirmMerge} disabled={merging}>
                {merging ? 'Merging...' : 'Merge'}
              </button>
              <button className="merge-btn-cancel" onClick={() => setTarget(null)} disabled={merging}>
                Back
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="merge-modal-header">
              <h3>Merge with...</h3>
              <button className="merge-modal-close" onClick={onClose} aria-label="Close">×</button>
            </div>

            <input
              type="text"
              className="merge-search-input"
              placeholder="Search people..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
              autoFocus
            />

            {loading && <div className="people-loading">Loading people...</div>}
            {loadError && <div className="error">{loadError}</div>}

            {!loading && !loadError && (
              <div className="merge-candidate-list">
                {filtered.length === 0 && (
                  <div className="merge-empty">No matching people.</div>
                )}
                {filtered.map(candidate => (
                  <div
                    key={candidate.id}
                    className="merge-candidate-row"
                    onClick={() => setTarget(candidate)}
                  >
                    <PersonCover person={candidate} />
                    <div className="merge-candidate-info">
                      <div className="merge-candidate-name">{candidate.display_name}</div>
                      <div className="merge-candidate-count">
                        {candidate.face_count} photo{candidate.face_count === 1 ? '' : 's'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function PersonDetail({ personId, onBack }) {
  const [person, setPerson] = useState(null)
  const [results, setResults] = useState([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lightboxIndex, setLightboxIndex] = useState(null)

  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [saving, setSaving] = useState(false)

  const [showMergeModal, setShowMergeModal] = useState(false)
  const [mergeStatus, setMergeStatus] = useState(null)

  // Explicit date range filter for this person's photo grid — in
  // loadPage's own dependency array below, so simply changing either
  // value gives loadPage a new identity, which the effect right after
  // it already reacts to (same mechanism that reloads on personId
  // changing) — no separate handler functions needed here, unlike the
  // Library page's date range (see App.jsx), which manages its own
  // query state outside of a reactive effect.
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const loadPage = useCallback((off, append = false) => {
    setLoading(true)
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(off) })
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    fetch(`${API_BASE}/people/${personId}/files?${params.toString()}`)
      .then(r => {
        if (!r.ok) throw new Error(`API returned ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (!Array.isArray(data.files)) throw new Error('Unexpected response shape')
        setPerson(data.person)
        setResults(prev => append ? [...prev, ...data.files] : data.files)
        setTotal(data.total)
        setError(null)
      })
      .catch(() => setError("Could not load this person's photos — the API endpoint may be missing or not restarted yet."))
      .finally(() => setLoading(false))
  }, [personId, dateFrom, dateTo])

  useEffect(() => {
    setResults([])
    setOffset(0)
    setMergeStatus(null)
    loadPage(0)
  }, [personId, loadPage])

  const loadMore = () => {
    const next = offset + PAGE_SIZE
    setOffset(next)
    loadPage(next, true)
  }

  const clearDateRange = () => {
    setDateFrom('')
    setDateTo('')
  }

  const startEditingName = () => {
    setNameInput(person?.name || '')
    setEditingName(true)
  }

  const saveName = async () => {
    const trimmed = nameInput.trim()
    if (!trimmed) return
    setSaving(true)
    try {
      const r = await fetch(`${API_BASE}/people/${personId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      })
      if (r.ok) {
        const data = await r.json()
        setPerson(prev => ({ ...prev, name: data.name, display_name: data.name }))
        setEditingName(false)
      }
    } finally {
      setSaving(false)
    }
  }

  const handleMerged = (mergedFrom, reassigned) => {
    setShowMergeModal(false)
    setMergeStatus(
      `Merged ${reassigned} face${reassigned === 1 ? '' : 's'} from "${mergedFrom.display_name}" into ${person.display_name}.`
    )
    // The keeper's face count/photos just changed — reload from scratch
    // rather than trying to patch the existing results in place.
    setOffset(0)
    loadPage(0)
  }

  const { sorted: sortedResults, groups: groupedResults } = groupByMonth(results)

  return (
    <div className="person-detail">
      <button className="people-back-btn" onClick={onBack}>&larr; All people</button>

      {person && (
        <div className="person-detail-header">
          {editingName ? (
            <div className="person-name-edit">
              <input
                type="text"
                value={nameInput}
                onChange={e => setNameInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') saveName()
                  if (e.key === 'Escape') setEditingName(false)
                }}
                autoFocus
              />
              <button onClick={saveName} disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
              <button onClick={() => setEditingName(false)}>Cancel</button>
            </div>
          ) : (
            <h2 className="person-detail-name" onClick={startEditingName} title="Click to rename">
              {person.display_name}
            </h2>
          )}

          <div className="person-detail-header-row">
            <div className="person-detail-count">{total.toLocaleString()} photo{total === 1 ? '' : 's'}</div>
            <button className="merge-trigger-btn" onClick={() => setShowMergeModal(true)}>
              Merge with...
            </button>
          </div>

          <div className="date-range-filters">
            <label className="date-range-label">
              From
              <input
                type="date"
                className="date-range-input"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={e => setDateFrom(e.target.value)}
              />
            </label>
            <label className="date-range-label">
              To
              <input
                type="date"
                className="date-range-input"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={e => setDateTo(e.target.value)}
              />
            </label>
            {(dateFrom || dateTo) && (
              <button type="button" className="date-range-clear" onClick={clearDateRange}>
                Clear dates
              </button>
            )}
          </div>

          {mergeStatus && <div className="merge-status">{mergeStatus}</div>}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {groupedResults.map(group => (
        <div key={group.label} className="date-group">
          <div className="date-group-header">{group.label}</div>
          <div className="file-grid">
            {group.files.map(file => {
              const idx = sortedResults.indexOf(file)
              return (
                <div
                  key={file.id}
                  className="file-row search-result"
                  onClick={() => setLightboxIndex(idx)}
                  style={{ cursor: 'pointer' }}
                >
                  <img
                    className="file-thumb"
                    src={`${API_BASE}/files/${file.id}/thumbnail`}
                    alt=""
                    loading="lazy"
                    onError={e => { e.target.style.display = 'none' }}
                  />
                  <span className={`badge ${file.is_image ? 'img' : 'vid'}`}>
                    {file.is_image ? 'IMG' : 'VID'}
                  </span>
                  <div className="file-row-main">
                    <span className="file-path">{file.path}</span>
                    {file.caption && <span className="file-caption">{file.caption}</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {results.length < total && (
        <button className="load-more" onClick={loadMore} disabled={loading}>
          {loading ? 'Loading...' : `Load more (${(total - results.length).toLocaleString()} remaining)`}
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

      {showMergeModal && person && (
        <MergeModal
          keeperPerson={person}
          onClose={() => setShowMergeModal(false)}
          onMerged={handleMerged}
        />
      )}
    </div>
  )
}

export default function People() {
  const [selectedPersonId, setSelectedPersonId] = useState(null)

  if (selectedPersonId !== null) {
    return <PersonDetail personId={selectedPersonId} onBack={() => setSelectedPersonId(null)} />
  }
  return <PeopleGrid onSelectPerson={setSelectedPersonId} />
}