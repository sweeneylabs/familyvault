import { useEffect, useCallback, useState } from 'react'
import './Lightbox.css'
import NamePicker from './NamePicker'
import {
  formatFullDate,
  locationLabel,
  displayCameraModel,
  isLikelyScreenshot,
  videoCategoryLabel,
} from './mediaLabels'
import { canEdit } from './access'

// Derived from the page's own hostname rather than hardcoded — see the
// matching comment in App.jsx for why a hardcoded 'localhost' breaks
// when this page is opened from another device on the network.
const API_BASE = `http://${window.location.hostname}:8000`

// One face detected in the currently-open photo. Shows a cropped face
// thumbnail (from *this* photo specifically — not the person's general
// cover photo, which could be a different picture entirely) plus their
// name, or "Unknown Person #N" if not yet named. On the Mac Mini
// (canEdit), clicking opens a popover holding the shared NamePicker —
// a name box that also lists already-named people matching what's
// typed, with a merge confirmation if one is picked — right there,
// without leaving the lightbox. On any other device the chip is
// display-only. `error` is a "name already used" (or other save
// failure) message from the last attempt, shown inside the picker.
function FaceChip({ person, isOpen, onToggle, onSave, onInputChange, onMerged, saving, error }) {
  const [imgFailed, setImgFailed] = useState(false)

  const initial = person.display_name.charAt(0).toUpperCase()

  return (
    <div className="lightbox-face-chip-wrap">
      <button
        type="button"
        className="lightbox-face-chip"
        onClick={(e) => {
          e.stopPropagation()
          if (canEdit) onToggle(isOpen ? null : person.person_id)
        }}
        title={canEdit ? (person.name ? `Rename ${person.name}` : 'Name this person') : undefined}
        style={canEdit ? undefined : { cursor: 'default' }}
      >
        {imgFailed ? (
          <div className="lightbox-face-avatar lightbox-face-avatar-placeholder">{initial}</div>
        ) : (
          <img
            className="lightbox-face-avatar"
            src={`${API_BASE}/faces/${person.face_id}/thumbnail`}
            alt=""
            onError={() => setImgFailed(true)}
          />
        )}
        <span className="lightbox-face-name">{person.display_name}</span>
      </button>

      {canEdit && isOpen && (
        <div className="lightbox-name-popover" onClick={(e) => e.stopPropagation()}>
          <NamePicker
            personId={person.person_id}
            currentName={person.name}
            displayName={person.display_name}
            initialValue={person.name || ''}
            saving={saving}
            error={error}
            onInputChange={onInputChange}
            onSave={(name) => onSave(person.person_id, name)}
            onCancel={() => onToggle(null)}
            onMerged={(target, reassigned) => onMerged(person, target, reassigned)}
          />
        </div>
      )}
    </div>
  )
}

// `onPersonMerged(mergedPersonId, target, reassigned)` is optional — if
// given, it's called after a face chip's person has been merged into an
// already-named one (`target`), so a page that's showing that person
// (e.g. the People page) can react, since they no longer exist.
export default function Lightbox({ files, index, onClose, onNavigate, onPersonMerged }) {
  const file = files[index]

  const [peopleInPhoto, setPeopleInPhoto] = useState([])
  const [peopleLoading, setPeopleLoading] = useState(false)
  const [peopleError, setPeopleError] = useState(null)
  const [openPersonId, setOpenPersonId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [nameError, setNameError] = useState(null)

  const goPrev = useCallback(() => {
    if (index > 0) onNavigate(index - 1)
  }, [index, onNavigate])

  const goNext = useCallback(() => {
    if (index < files.length - 1) onNavigate(index + 1)
  }, [index, files.length, onNavigate])

  // Locks the page's own scroll for as long as the lightbox is mounted,
  // so scroll input has nowhere to go but into .lightbox-content's own
  // overflow-y: auto — without this, scrolling while hovering the
  // lightbox scrolls the page behind it instead, since a position:fixed
  // overlay doesn't block the underlying document from scrolling on its
  // own. Restores whatever the body's overflow was before, on close.
  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [])

  useEffect(() => {
    const handleKey = (e) => {
      // While typing in the name popover, arrow keys should move the
      // text cursor, not navigate to the next/previous photo — and
      // Escape should be handled by the input itself (closing just the
      // popover), not bubble up to close the whole lightbox.
      const isTyping = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'
      if (isTyping) return

      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') goPrev()
      if (e.key === 'ArrowRight') goNext()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose, goPrev, goNext])

  // Load who's in the currently-displayed photo whenever it changes,
  // and close any popover left open from the previous photo — it
  // would otherwise silently point at the wrong file's person list.
  useEffect(() => {
    if (!file) return
    setOpenPersonId(null)
    setNameError(null)
    setPeopleLoading(true)
    setPeopleError(null)
    fetch(`${API_BASE}/files/${file.id}/people`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`)
        return r.json()
      })
      .then((data) => setPeopleInPhoto(Array.isArray(data.people) ? data.people : []))
      .catch(() => setPeopleError('Could not load people for this photo.'))
      .finally(() => setPeopleLoading(false))
  }, [file?.id])

  // Opening, closing, or switching which chip's popover is open always
  // starts from a clean slate — a "name already used" message from an
  // earlier attempt shouldn't linger onto a different chip or a
  // reopened popover.
  const handleToggle = (personId) => {
    setNameError(null)
    setOpenPersonId(personId)
  }

  // Names must be unique (see database.set_person_name()) — the API
  // answers 409 with a ready-to-show message naming who already has
  // it. The popover stays open on any failure so the name can be
  // edited and retried, with the reason shown instead of failing
  // silently.
  const handleSaveName = async (personId, rawName) => {
    if (!canEdit) return
    const trimmed = rawName.trim()
    if (!trimmed) return
    setSaving(true)
    setNameError(null)
    try {
      const r = await fetch(`${API_BASE}/people/${personId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      })
      if (r.ok) {
        const data = await r.json()
        setPeopleInPhoto((prev) =>
          prev.map((p) =>
            p.person_id === personId ? { ...p, name: data.name, display_name: data.name } : p
          )
        )
        setOpenPersonId(null)
      } else if (r.status === 409) {
        const data = await r.json()
        setNameError(data.detail)
      } else {
        setNameError('Could not save the name — please try again.')
      }
    } catch {
      setNameError('Could not save the name — please try again.')
    } finally {
      setSaving(false)
    }
  }

  // A chip's person was just merged into an already-named person
  // (`target`), so the unnamed person no longer exists — every chip in
  // this photo that pointed at them (a person can appear more than once
  // in a photo) switches over to the surviving person, then the parent
  // page, if it cares, is told.
  const handleMerged = (merged, target, reassigned) => {
    setNameError(null)
    setPeopleInPhoto((prev) =>
      prev.map((p) =>
        p.person_id === merged.person_id
          ? { ...p, person_id: target.id, name: target.name, display_name: target.name }
          : p
      )
    )
    setOpenPersonId(null)
    if (onPersonMerged) onPersonMerged(merged.person_id, target, reassigned)
  }

  if (!file) return null

  const mediaUrl = `${API_BASE}/files/${file.id}/media`
  const filename = file.path.split('/').pop()

  const fullDate = formatFullDate(file.date_taken)
  const location = locationLabel(file)
  const camera = file.camera_model ? displayCameraModel(file.camera_model) : null
  const screenshot = isLikelyScreenshot(file)
  const videoCategory = file.is_video ? videoCategoryLabel(file) : null

  return (
    <div className="lightbox-overlay" onClick={onClose}>
      <button className="lightbox-close" onClick={onClose} aria-label="Close">×</button>

      {index > 0 && (
        <button
          className="lightbox-nav lightbox-prev"
          onClick={(e) => { e.stopPropagation(); goPrev() }}
          aria-label="Previous"
        >
          ‹
        </button>
      )}

      {index < files.length - 1 && (
        <button
          className="lightbox-nav lightbox-next"
          onClick={(e) => { e.stopPropagation(); goNext() }}
          aria-label="Next"
        >
          ›
        </button>
      )}

      <div
        className="lightbox-content"
        onClick={(e) => {
          e.stopPropagation()
          // A click anywhere in the content area that isn't a face chip
          // (chips call their own stopPropagation) closes any open
          // name popover, rather than leaving it stranded open.
          if (openPersonId !== null) handleToggle(null)
        }}
      >
        {file.is_video ? (
          <video
            key={file.id}
            className="lightbox-media"
            src={mediaUrl}
            controls
            autoPlay
          />
        ) : (
          <img className="lightbox-media" src={mediaUrl} alt="" />
        )}

        <div className="lightbox-info">
          <div className="lightbox-filename">{filename}</div>
          {file.caption && <div className="lightbox-caption">{file.caption}</div>}

          {(fullDate || location || camera || videoCategory || screenshot) && (
            <div className="lightbox-meta-tags">
              {fullDate && <span className="lightbox-meta-tag">{fullDate}</span>}
              {location && <span className="lightbox-meta-tag">{location}</span>}
              {camera && <span className="lightbox-meta-tag">{camera}</span>}
              {videoCategory && <span className="lightbox-meta-tag">{videoCategory}</span>}
              {screenshot && <span className="lightbox-meta-tag">Screenshot</span>}
            </div>
          )}

          {peopleLoading && <div className="lightbox-people-status">Loading people...</div>}
          {peopleError && <div className="lightbox-people-status lightbox-people-error">{peopleError}</div>}
          {!peopleLoading && !peopleError && peopleInPhoto.length > 0 && (
            <div className="lightbox-people-row">
              {peopleInPhoto.map((person) => (
                <FaceChip
                  key={person.face_id}
                  person={person}
                  isOpen={openPersonId === person.person_id}
                  onToggle={handleToggle}
                  onSave={handleSaveName}
                  onInputChange={() => setNameError(null)}
                  onMerged={handleMerged}
                  saving={saving}
                  error={nameError}
                />
              ))}
            </div>
          )}

          <div className="lightbox-counter">{index + 1} of {files.length}</div>
        </div>
      </div>
    </div>
  )
}
