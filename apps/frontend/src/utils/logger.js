const DEFAULT_COMPONENT = 'FE'

function formatTs() {
  return new Date().toISOString()
}

function serializePayload(payload) {
  if (payload === undefined) return ''
  try {
    return JSON.stringify(payload)
  } catch {
    return '"[unserializable]"'
  }
}

export function createLogger(component = DEFAULT_COMPONENT) {
  const base = String(component || DEFAULT_COMPONENT)
  const write = (level, event, payload) => {
    const ts = formatTs()
    const ev = event ? String(event) : '-'
    const header = `ts=${ts} level=${level} component=${base} event=${ev}`
    const serialized = serializePayload(payload)
    if (serialized) {
      console[level](header, payload)
    } else {
      console[level](header)
    }
  }
  return {
    info: (event, payload) => write('info', event, payload),
    warn: (event, payload) => write('warn', event, payload),
    error: (event, payload) => write('error', event, payload),
  }
}
