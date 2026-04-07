export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8102'

function toQuery(params = {}) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null) return
    if (typeof value === 'string' && value.trim() === '') return
    if (Array.isArray(value)) {
      if (value.length > 0) q.set(key, value.join(','))
      return
    }
    q.set(key, String(value))
  })
  return q.toString()
}

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const requestUrl = `${API_BASE}${path}`
  console.debug(`[api] request start ${method} ${requestUrl}`)
  let res
  try {
    res = await fetch(requestUrl, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    })
  } catch (error) {
    const message = String(error?.message || error || '')
    if (message.includes('Failed to fetch') || message.includes('ERR_CONNECTION_REFUSED') || message.includes('NetworkError')) {
      console.error(`[api] network failure ${method} ${requestUrl}`, message)
      throw new Error(`Backend offline at ${API_BASE}`)
    }
    console.error(`[api] fetch error ${method} ${requestUrl}`, error)
    throw error
  }
  if (!res.ok) {
    const text = await res.text()
    console.error(`[api] response error ${method} ${requestUrl} status=${res.status}`, text)
    throw new Error(`API ${res.status}: ${text}`)
  }
  console.debug(`[api] response success ${method} ${requestUrl} status=${res.status}`)
  return res.json()
}

export const api = {
  health: () => request('/health'),
  dashboard: () => request('/api/dashboard'),
  jobs: (params) => request(`/api/jobs?${toQuery(params)}`),
  deleteJobs: (jobIds) => request('/api/jobs', { method: 'DELETE', body: JSON.stringify({ job_ids: jobIds || [] }) }),
  jobDetail: (id, constraintMode = 'medium') => request(`/api/jobs/${id}?${toQuery({ constraint_mode: constraintMode })}`),
  jobCvPreview: (id, constraintMode = 'medium') => request(`/api/jobs/${id}/cv-preview?${toQuery({ constraint_mode: constraintMode })}`),
  updateJobPriority: (jobId, payload) => request(`/api/jobs/${jobId}/priority`, { method: 'PATCH', body: JSON.stringify(payload) }),
  markJobAppliedManual: (jobId, payload) => request(`/api/jobs/${jobId}/manual-apply`, { method: 'PATCH', body: JSON.stringify(payload || {}) }),
  updateCompanyPriority: (payload) => request('/api/companies/priority', { method: 'PATCH', body: JSON.stringify(payload) }),
  countries: () => request('/api/countries'),
  regions: () => request('/api/regions'),
  regionCountries: () => request('/api/regions/countries'),
  programmingLanguages: () => request('/api/programming-languages'),
  programmingLanguageGroups: () => request('/api/programming-languages/groups'),
  reposts: (params) => request(`/api/analytics/reposts?${toQuery(params)}`),
  countriesOverview: () => request('/api/analytics/countries-overview'),
  appliedJobsTrend: (params) => request(`/api/analytics/applied-jobs-trend?${toQuery(params)}`),
  appliedJobsTrendDebug: () => request('/api/analytics/applied-jobs-trend/debug'),
  schedules: () => request('/api/schedules'),
  runs: (limit = 50) => request(`/api/runs?limit=${limit}`),
  forceStopRun: (runId) => request(`/api/runs/${runId}/force-stop`, { method: 'POST' }),
  pauseRun: (runId) => request(`/api/runs/${runId}/pause`, { method: 'POST' }),
  deleteRun: (runId) => request(`/api/runs/${runId}`, { method: 'DELETE' }),
  resumeRun: (runId) => request(`/api/runs/${runId}/resume`, { method: 'POST' }),
  learningTopics: () => request('/api/learning/topics'),
  learningQuiz: (params) => request(`/api/learning/quiz?${toQuery(params)}`),
  submitLearningQuiz: (payload) => request('/api/learning/quiz/submit', { method: 'POST', body: JSON.stringify(payload) }),
  learningQuizHistory: (limit = 20) => request(`/api/learning/quiz/history?${toQuery({ limit })}`),
  learningKnowledge: (params) => request(`/api/learning/knowledge?${toQuery(params)}`),
  runLearningEtl: (payload) => request('/api/actions/run-learning-etl', { method: 'POST', body: JSON.stringify(payload || {}) }),
  createSchedule: (payload) => request('/api/schedules', { method: 'POST', body: JSON.stringify(payload) }),
  runScheduleNow: (id) => request(`/api/schedules/${id}/run-now`, { method: 'POST' }),
  updateSchedule: (id, payload) => request(`/api/schedules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateScheduleOccurrence: (id, payload) => request(`/api/schedules/${id}/occurrence`, { method: 'PATCH', body: JSON.stringify(payload) }),
  cancelScheduleOccurrence: (id, overrideId) => request(`/api/schedules/${id}/occurrence/${overrideId}`, { method: 'DELETE' }),
  deleteSchedule: (id) => request(`/api/schedules/${id}`, { method: 'DELETE' }),
  triggerAction: (payload) => request('/api/actions/trigger', { method: 'POST', body: JSON.stringify(payload) }),
  evaluateFit: (payload) => request('/api/fit/evaluate', { method: 'POST', body: JSON.stringify(payload) }),
  rewriteRenderCv: (payload) => request('/api/cv/rewrite-render', { method: 'POST', body: JSON.stringify(payload) }),
  rewriteRenderCvFromJob: (jobId, payload) => request(`/api/cv/rewrite-render/from-job/${jobId}`, { method: 'POST', body: JSON.stringify(payload) }),
  rewriteRenderCvFromJobs: (payload) => request('/api/cv/rewrite-render/from-jobs', { method: 'POST', body: JSON.stringify(payload) }),
  linkedinApply: (payload) => request('/api/linkedin/apply', { method: 'POST', body: JSON.stringify(payload) }),
  cvFiles: (ext = 'pdf,docx') => request(`/api/cv/files?${toQuery({ ext })}`),
  fileContentUrl: (path) => `${API_BASE}/api/files/content?path=${encodeURIComponent(path || '')}`,
  fileText: (path) => request(`/api/files/text?${toQuery({ path })}`),
}
