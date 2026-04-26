// Warning severity parser — matches the [INFO]/[WARN]/[ERROR] prefix the
// backend stamps on entries inside `task.error_message` (a `" | "`-joined
// string of multiple warnings).
//
// Why prefix-encoded instead of a separate column:
//   The backend used to dump everything into `error_message` regardless
//   of severity, leaving the UI no way to distinguish "task succeeded
//   with informational drop notes" from "task failed with quota error".
//   Adding a JSON column would have required an Alembic migration; using
//   inline `[LEVEL]` prefixes keeps the wire format string-compatible
//   with old-form clients (un-prefixed = WARN by default).

export type Severity = 'info' | 'warning' | 'error'

export interface ParsedWarning {
  severity: Severity
  message: string
}

const PREFIX_RE = /^\[(INFO|WARN|ERROR)\]/i

export function parseWarning(raw: string): ParsedWarning {
  const m = PREFIX_RE.exec(raw)
  if (!m) {
    // Backwards-compat: un-prefixed strings are treated as warnings (the
    // legacy default before severity grading shipped).
    return { severity: 'warning', message: raw.trim() }
  }
  const tag = m[1].toUpperCase()
  const message = raw.slice(m[0].length).trim()
  if (tag === 'INFO') return { severity: 'info', message }
  if (tag === 'ERROR') return { severity: 'error', message }
  return { severity: 'warning', message }
}

export function parseWarningList(rawCombined: string | null | undefined): ParsedWarning[] {
  if (!rawCombined) return []
  return rawCombined.split(' | ').map(parseWarning).filter(p => p.message)
}

// Highest severity in a list (error > warning > info). Used by callers
// that want to colour a parent container (e.g. list-row text) by the
// "worst" severity present.
export function maxSeverity(warnings: ParsedWarning[]): Severity | null {
  if (warnings.length === 0) return null
  if (warnings.some(w => w.severity === 'error')) return 'error'
  if (warnings.some(w => w.severity === 'warning')) return 'warning'
  return 'info'
}

// Filter out info-level entries — used by list page to hide noise on
// successful tasks. Detail page shows all severities.
export function filterShown(warnings: ParsedWarning[]): ParsedWarning[] {
  return warnings.filter(w => w.severity !== 'info')
}
