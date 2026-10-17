// Shared display-formatting helpers for media file metadata — camera
// names, screenshot detection, video category, location, and named
// people labels. Extracted out of App.jsx so Lightbox.jsx can reuse
// the exact same logic rather than a second, possibly-diverging copy.

export const CAMERA_DISPLAY_NAMES = {
  'DSC-W1': 'Sony Cyber-shot DSC-W1',
  'DSC-T33': 'Sony Cyber-shot DSC-T33',
  'DSC-S600': 'Sony Cyber-shot DSC-S600',
  'SV-AS10': 'Samsung SV-AS10 Camcorder',
  'FC1102': 'GoPro Hero',
  'DMC-GH3': 'Panasonic Lumix GH3',
  'DMC-ZS10': 'Panasonic Lumix ZS10',
  'NEX-3N': 'Sony Alpha NEX-3N',
  'ILCE-6500': 'Sony Alpha a6500',
  'ILCE-5100': 'Sony Alpha a5100',
  'SM-N900V': 'Samsung Galaxy Note 3',
  'SAMSUNG-SGH-I537': 'Samsung Galaxy S4 Active',
  'SAMSUNG-SGH-I337': 'Samsung Galaxy S4',
  'C730UZ': 'Olympus Camedia C-730',
  'USB Camera': 'Webcam',
  'Hero3-Silver Edition': 'GoPro Hero3 Silver',
}

export function displayCameraModel(raw) {
  return CAMERA_DISPLAY_NAMES[raw] || raw
}

export function isLikelyScreenshot(file) {
  return file.extension === '.png' && !file.camera_model
}

export function resolutionTier(width) {
  if (!width) return null
  if (width >= 3840) return '4K'
  if (width >= 1920) return '1080p'
  if (width >= 1280) return '720p'
  return 'SD'
}

export function lengthCategory(seconds) {
  if (seconds == null) return null
  if (seconds < 4) return 'Live Photo'
  if (seconds < 30) return 'Short clip'
  if (seconds < 120) return 'Video'
  return 'Long video'
}

export function videoCategoryLabel(file) {
  const tier = resolutionTier(file.width)
  const length = lengthCategory(file.duration_seconds)
  if (tier && length) return `${tier} · ${length}`
  return tier || length
}

// Builds a "City, State, Country" label from whichever location fields
// are present, gracefully degrading (e.g. "Paris, France" for a location
// with no state/admin1). Returns null if the file has no location data
// at all — reverse geocoding only ever runs against files that have GPS
// coordinates, so most of the library will have no location yet.
export function locationLabel(file) {
  const parts = [file.city, file.state, file.country].filter(Boolean)
  return parts.length ? parts.join(', ') : null
}

// Builds a comma-joined label from a file's named people (e.g. "Patrick,
// Tamika"). Only ever contains named people — see
// database.get_named_people_for_files() — since an unnamed "Unknown
// Person #N" isn't meaningful in a browsing tag. Returns null if the
// file has no `people` field at all (e.g. results not produced by the
// /search endpoint) or no named people were found in it.
export function peopleLabel(file) {
  if (!file.people || !file.people.length) return null
  return file.people.join(', ')
}

// Full day-level date for the lightbox metadata panel — distinct from
// the monthYearLabel() helpers in App.jsx/People.jsx, which only need
// month/year for grouping section headers, not the specific day.
export function formatFullDate(dateTaken) {
  if (!dateTaken) return null
  const d = new Date(dateTaken)
  if (isNaN(d.getTime())) return null
  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}