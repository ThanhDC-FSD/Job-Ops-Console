# Frontend Analytics and Interaction Excerpt

This excerpt shows part of the React-side analytics and interaction model, including persisted filters, sorting, and data refresh behavior.

```jsx
const analyticsView = useMemo(() => readStoredState(ANALYTICS_STATE_KEY, {}), [])
const [filters, setFilters] = useState(() => ({
  countries: [],
  company: '',
  min_reposts: '1',
  limit: '200',
  ...(analyticsView?.filters || {})
}))
const [rows, setRows] = useState([])
const [sort, setSort] = useState({ key: 'repost_count', dir: 'desc' })

async function runAnalytics() {
  setLoading(true)
  setError('')
  try {
    const payload = {
      ...filters,
      min_reposts: String(Math.max(1, Number(filters.min_reposts) || 1)),
    }
    const res = await api.reposts(payload)
    setRows(res.items || [])
  } catch (e) {
    setRows([])
    setError(String(e?.message || e))
  } finally {
    setLoading(false)
  }
}

useEffect(() => {
  writeStoredState(ANALYTICS_STATE_KEY, { filters, page, pageSize })
}, [filters, page, pageSize])
```

What this demonstrates:

- practical state persistence for operator workflows
- UI-focused analytics without requiring a full page reload
- product-minded frontend behavior for repeated operational use
