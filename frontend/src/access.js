// Whether this page was loaded on the Mac Mini itself. The API only
// accepts rename/merge requests from its own loopback address (see
// require_local() in api.py), and API_BASE in App.jsx/People.jsx/
// Lightbox.jsx is built from window.location.hostname — so a page
// opened at http://localhost:5173 talks to the API from loopback and
// can edit, while a page opened at the Mac's LAN IP (from any device,
// including the Mac itself) is view-only.
//
// This only controls what the UI shows. The real enforcement is the
// 403 from the API, so hiding a control here is a convenience, not a
// security boundary.

const LOCAL_HOSTNAMES = ['localhost', '127.0.0.1', '[::1]', '::1']

export const canEdit = LOCAL_HOSTNAMES.includes(window.location.hostname)
