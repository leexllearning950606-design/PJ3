export function connectSSE(taskId) {
  const url = `/api/events/${taskId}`
  const source = new EventSource(url)

  const listeners = {}

  source.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.progress) listeners.progress(data)
  })
  source.addEventListener('grid', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.grid) listeners.grid(data)
  })
  source.addEventListener('interactive', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.interactive) listeners.interactive(data)
  })
  source.addEventListener('complete', (e) => {
    const data = JSON.parse(e.data)
    if (listeners.complete) listeners.complete(data)
  })
  source.addEventListener('error', (e) => {
    let data = {}
    try { data = JSON.parse(e.data) } catch (_) {}
    if (listeners.error) listeners.error(data)
  })
  source.addEventListener('ping', () => {})

  return {
    on(event, fn) { listeners[event] = fn; return this },
    close() { source.close() },
  }
}
