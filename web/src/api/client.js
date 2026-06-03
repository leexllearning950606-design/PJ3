const BASE = '/api'

export async function generate(userInput) {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: userInput }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function interact(taskId, action, description) {
  const res = await fetch(`${BASE}/tasks/${taskId}/interact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, description }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function markDone(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}/done`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchTasks(search = '', page = 1, limit = 20) {
  const params = new URLSearchParams({ search, page, limit })
  const res = await fetch(`${BASE}/tasks?${params}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchTask(taskId) {
  const res = await fetch(`${BASE}/tasks/${taskId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchPreferences() {
  const res = await fetch(`${BASE}/preferences`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updatePreferences(category, tags) {
  const res = await fetch(`${BASE}/preferences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category, tags }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function resetPreferences() {
  const res = await fetch(`${BASE}/preferences`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchStatus() {
  const res = await fetch(`${BASE}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
