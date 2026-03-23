# Frontend Analytics And Interaction Excerpt

This excerpt shows how the React console turns raw backend metrics into **interactive operational views** without burying logic in one giant component.

## Applied Trend Timeline

The applied trend chart stores zoom state, supports wheel zoom, drag-to-pan, and keeps the latest operator position in session storage.

```jsx
function handleChartWheel(event) {
  const node = scrollRef.current
  if (!node) return
  const rect = node.getBoundingClientRect()
  const pointerRatio = rect.width > 0
    ? (event.clientX - rect.left + node.scrollLeft) / Math.max(node.scrollWidth, 1)
    : 0.5
  const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX
  if (!delta) return

  const nextZoom = Math.max(0.25, Math.min(3, Math.round((zoomX + (delta < 0 ? 0.15 : -0.15)) * 100) / 100))
  if (nextZoom !== zoomX) {
    const currentAbsoluteX = pointerRatio * node.scrollWidth
    savedScrollLeftRef.current = Math.max(0, currentAbsoluteX - ((event.clientX - rect.left) || 0))
    setZoomX(nextZoom)
  }
  event.preventDefault()
}
```

Why this matters:

- long operator timelines remain usable without leaving the current page
- zoom state persists across navigation, which helps daily review work
- the interaction cost stays low even when the dataset grows over time

## Country Density Map

The world map keeps zoom and pan state locally and converts backend country counts into a navigable heat-style layer.

```jsx
const densityMap = useMemo(() => {
  const map = new Map()
  for (const item of items || []) {
    const country = String(item?.country || '').trim()
    const key = normalizeCountryKey(country)
    if (!key) continue
    const current = map.get(key) || { country, jobs: 0, applied_jobs: 0 }
    current.jobs += Number(item?.jobs || 0)
    current.applied_jobs += Number(item?.applied_jobs || 0)
    map.set(key, current)
  }
  return map
}, [items])

function updateTooltip(event, item, featureName) {
  const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect()
  if (!rect) return
  setTooltip({
    x: event.clientX - rect.left + 12,
    y: event.clientY - rect.top + 12,
    country: item?.country || featureName,
    jobs: Number(item?.jobs || 0),
    appliedJobs: Number(item?.applied_jobs || 0),
  })
}
```

Why this matters:

- analytics stay actionable because every country interaction can open filtered job queues
- the map gives both coverage and application context instead of only one metric
- view state is kept in the browser, which fits a local-first tool on lower-spec hardware

## Analytics-To-Workflow Bridge

The analytics screen is not read-only. It can push the operator straight back into a filtered jobs view.

```jsx
function openJobsWithPreset(preset) {
  setJobsPreset({ ...preset, limit: '50', offset: '0' })
  setActive('jobs')
}

if (active === 'dashboard') {
  return <DashboardTab ... onOpenJobs={openJobsWithPreset} />
}
if (active === 'analytics') {
  return <AnalyticsTab ... onOpenJobs={openJobsWithPreset} />
}
```

Why this matters:

- charts do not become dead-end reporting widgets
- operators can jump from evidence to action in one click
- the console feels like one workflow rather than isolated pages

Design patterns showcased:

- stateful analytics components
- persistent UI state for local-first workflows
- drill-down navigation from metrics into actionable queues
