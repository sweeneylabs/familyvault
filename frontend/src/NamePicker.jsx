import { useState, useEffect } from 'react'
import './NamePicker.css'

// Derived from the page's own hostname rather than hardcoded — see the
// matching comment in App.jsx for why a hardcoded 'localhost' breaks
// when this page is opened from another device on the network.
const API_BASE = `http://${window.location.hostname}:8000`

const SEARCH_DEBOUNCE_MS = 250
const MAX_MATCHES = 8

// Small round cover face for an already-named person, with a letter
// placeholder if they have no cover or it fails to load. Self-contained
// (rather than reusing People.jsx's PersonCover) so this component
// looks the same wherever it's used — the People page and the lightbox.
function MatchAvatar({ person }) {
  const [failed, setFailed] = useState(false)
  const label = person.display_name || person.name || '?'

  if (!person.has_cover || failed) {
    return (
      <div className="name-picker-avatar name-picker-avatar-placeholder">
        {label.charAt(0).toUpperCase()}
      </div>
    )
  }

  return (
    <img
      className="name-picker-avatar"
      src={`${API_BASE}/people/${person.id}/cover`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

// The shared "name this person" control — a text box with Save/Cancel,
// plus, while naming someone who has no name yet, a live list of
// already-named people matching what's been typed (GET /people/search).
// Picking one asks whether to merge this person into them, with Merge
// and Cancel buttons (POST /people/{id}/merge, with the already-named
// person as the keeper so their name survives). Naming someone who
// already has a name never offers a merge — a taken name is just
// reported by the parent via `error` (the API's 409 message).
//
// Saving and the merge-complete reaction belong to the parent, since
// they differ by screen:
//   onSave(name)                  — parent PATCHes the name
//   onCancel()                    — parent closes the editor
//   onMerged(target, reassigned)  — a merge succeeded; this person no
//                                   longer exists, so parent should move
//                                   on to `target` (the surviving person)
//   onInputChange()               — typing happened; parent clears its error
//
// Props:
//   personId     — id of the person being named
//   currentName  — their current name, or null/'' if unnamed (decides
//                  whether merging is offered)
//   displayName  — how they're shown now ("Unknown Person #123"), for the
//                  confirmation text
//   photoCount   — optional, number of their photos, for the confirmation text
//   initialValue — starting text for the box
//   saving       — parent's save is in flight
//   error        — parent's save error message, if any
export default function NamePicker({
  personId,
  currentName,
  displayName,
  photoCount,
  initialValue,
  saving,
  error,
  onInputChange = () => {},
  onSave,
  onCancel,
  onMerged,
}) {
  const [value, setValue] = useState(initialValue || '')
  const [debouncedText, setDebouncedText] = useState('')
  const [result, setResult] = useState({ text: '', people: [], failed: false })

  const [target, setTarget] = useState(null)
  const [merging, setMerging] = useState(false)
  const [mergeError, setMergeError] = useState(null)

  const offerMerge = !currentName

  // Debounce what's been typed, so the lookup below runs once typing
  // pauses rather than on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedText(value.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [value])

  // Look up already-named people matching the (debounced) text. The
  // person being named is excluded server-side, so they can't match
  // themselves. `cancelled` drops the answer to a lookup that's been
  // superseded by newer typing.
  useEffect(() => {
    if (!offerMerge || !debouncedText) return
    let cancelled = false
    const params = new URLSearchParams({
      q: debouncedText,
      limit: String(MAX_MATCHES),
      exclude_id: String(personId),
    })
    fetch(`${API_BASE}/people/search?${params.toString()}`)
      .then(r => {
        if (!r.ok) throw new Error(`API returned ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (cancelled) return
        setResult({
          text: debouncedText,
          people: Array.isArray(data.people) ? data.people : [],
          failed: false,
        })
      })
      .catch(() => {
        if (!cancelled) setResult({ text: debouncedText, people: [], failed: true })
      })
    return () => { cancelled = true }
  }, [offerMerge, debouncedText, personId])

  // Only trust a result that belongs to the text currently being
  // searched for — anything older (or an emptied box) shows no list.
  const resultIsCurrent = offerMerge && debouncedText !== '' && result.text === debouncedText
  const matches = resultIsCurrent ? result.people : []
  const lookupFailed = resultIsCurrent && result.failed

  const cancelMerge = () => {
    setTarget(null)
    setMergeError(null)
  }

  // The already-named person is the keeper, so their name survives;
  // this person's faces move over to them and this person is deleted.
  // Irreversible — which is why this only runs from the confirmation
  // screen below.
  const confirmMerge = async () => {
    if (!target) return
    setMerging(true)
    setMergeError(null)
    try {
      const r = await fetch(`${API_BASE}/people/${target.id}/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loser_ids: [personId] }),
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

  if (target) {
    const photos = photoCount != null
      ? ` (${photoCount.toLocaleString()} photo${photoCount === 1 ? '' : 's'})`
      : ''

    return (
      <div className="name-picker">
        <div className="name-picker-confirm">
          <div className="name-picker-confirm-header">
            <MatchAvatar person={target} />
            <div className="name-picker-confirm-title">Merge into {target.name}?</div>
          </div>
          <p className="name-picker-confirm-detail">
            Everything currently tagged as <strong>{displayName}</strong>{photos} will be
            tagged as <strong>{target.name}</strong> instead. This can't be undone.
          </p>
          {mergeError && <div className="name-picker-error">{mergeError}</div>}
          <div className="name-picker-confirm-actions">
            <button type="button" className="name-picker-btn primary" onClick={confirmMerge} disabled={merging}>
              {merging ? 'Merging...' : 'Merge'}
            </button>
            <button type="button" className="name-picker-btn" onClick={cancelMerge} disabled={merging}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="name-picker">
      <div className="name-picker-row">
        <input
          className="name-picker-input"
          type="text"
          value={value}
          placeholder="Enter name"
          onChange={e => {
            setValue(e.target.value)
            onInputChange()
          }}
          onKeyDown={e => {
            if (e.key === 'Enter') onSave(value)
            if (e.key === 'Escape') onCancel()
          }}
          autoFocus
        />
        <button type="button" className="name-picker-btn primary" onClick={() => onSave(value)} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button type="button" className="name-picker-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>

      {error && <div className="name-picker-error">{error}</div>}

      {matches.length > 0 && (
        <div className="name-picker-matches">
          <div className="name-picker-hint">Already named — pick one if this is the same person:</div>
          {matches.map(match => (
            <button
              key={match.id}
              type="button"
              className="name-picker-match"
              onClick={() => setTarget(match)}
            >
              <MatchAvatar person={match} />
              <div className="name-picker-match-info">
                <div className="name-picker-match-name">{match.display_name}</div>
                <div className="name-picker-match-count">
                  {match.face_count} photo{match.face_count === 1 ? '' : 's'}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {lookupFailed && <div className="name-picker-status">Couldn't look up existing names.</div>}
    </div>
  )
}
