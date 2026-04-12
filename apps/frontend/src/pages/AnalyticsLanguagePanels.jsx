function formatCompactNumber(value) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric)) return '0'
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: numeric >= 1000 ? 1 : 0 }).format(numeric)
}

function formatSignedPercent(value) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric)) return '0%'
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(1)}%`
}

const LANGUAGE_TREND_COLORS = ['#0d6c5f', '#1455a1', '#cc5f16', '#8b2f8f', '#b42318', '#0f766e', '#6b46c1', '#475467']

function linePathFromPoints(points) {
  if (!Array.isArray(points) || points.length === 0) return ''
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
}

function LanguageTrendChart({ trend, t }) {
  const series = Array.isArray(trend?.daily_series) ? trend.daily_series : []
  const topLanguages = Array.isArray(trend?.top_languages) ? trend.top_languages : []
  if (!series.length || !topLanguages.length) return null
  const width = Math.max(860, series.length * 18)
  const height = 320
  const padLeft = 54
  const padRight = 18
  const padTop = 26
  const padBottom = 44
  const innerWidth = Math.max(1, width - padLeft - padRight)
  const innerHeight = Math.max(1, height - padTop - padBottom)
  const maxY = Math.max(
    1,
    ...series.flatMap((point) => topLanguages.map((item) => Number(point?.languages?.[item.language] || 0))),
  )
  const axisTicks = [0, 0.25, 0.5, 0.75, 1]
  const lines = topLanguages.map((item, index) => {
    const color = LANGUAGE_TREND_COLORS[index % LANGUAGE_TREND_COLORS.length]
    const points = series.map((point, pointIndex) => {
      const count = Number(point?.languages?.[item.language] || 0)
      const x = padLeft + (pointIndex / Math.max(1, series.length - 1)) * innerWidth
      const y = padTop + innerHeight - (count / maxY) * innerHeight
      return { x, y, count }
    })
    return { language: item.language, color, points }
  })
  return (
    <div className="language-trend-chart-wrap">
      <div className="language-trend-legend">
        {topLanguages.map((item, index) => (
          <span key={item.language}>
            <i className="legend-dot" style={{ background: LANGUAGE_TREND_COLORS[index % LANGUAGE_TREND_COLORS.length] }} />
            {item.language}
          </span>
        ))}
      </div>
      <div className="applied-chart-scroll">
        <svg className="applied-chart language-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t.analytics || 'Analytics'}>
          {axisTicks.map((tick) => {
            const y = padTop + innerHeight - innerHeight * tick
            const label = Math.round(maxY * tick)
            return (
              <g key={tick}>
                <line x1={padLeft} y1={y} x2={width - padRight} y2={y} className="chart-grid-line" />
                <text x={padLeft - 8} y={y + 4} textAnchor="end" className="chart-axis-text">{label}</text>
              </g>
            )
          })}
          <line x1={padLeft} y1={padTop + innerHeight} x2={width - padRight} y2={padTop + innerHeight} className="chart-grid-line" />
          {series.map((point, index) => {
            if (index % Math.max(1, Math.floor(series.length / 6)) !== 0 && index !== series.length - 1) return null
            const x = padLeft + (index / Math.max(1, series.length - 1)) * innerWidth
            return (
              <text key={point.date} x={x} y={height - 12} textAnchor="middle" className="chart-axis-text">
                {String(point.date || '').slice(5)}
              </text>
            )
          })}
          {lines.map((line) => (
            <path key={line.language} d={linePathFromPoints(line.points)} className="chart-line" style={{ stroke: line.color }} />
          ))}
          {lines.map((line) => (
            line.points.filter((_, index) => index === line.points.length - 1).map((point) => (
              <g key={`${line.language}-last`}>
                <circle cx={point.x} cy={point.y} r="4" style={{ fill: line.color, stroke: '#fff', strokeWidth: 2 }} />
                <text x={point.x + 8} y={point.y - 8} className="chart-axis-text">{line.language}</text>
              </g>
            ))
          ))}
        </svg>
      </div>
      <div className="applied-chart-hint muted">
        90-day local demand based on recent first-seen jobs. Counts represent language mentions per day, not unique developers.
      </div>
    </div>
  )
}

export function AnalyticsLanguagePanels({
  languageData,
  languageContext,
  languageContextLoading,
  languageContextError,
  languageAiInsights,
  languageAiLoading,
  languageAiError,
  onOpenLanguageJobs,
  onRefreshLanguageAiInsights,
  t,
}) {
  const topLanguageCards = Array.isArray(languageData?.top_languages) ? languageData.top_languages : []
  const regionBreakdown = Array.isArray(languageData?.region_breakdown) ? languageData.region_breakdown : []
  const macroCards = Array.isArray(languageContext?.macro_cards) ? languageContext.macro_cards : []
  const contextItems = Array.isArray(languageContext?.items) ? languageContext.items : []

  return (
    <>
      <div className="analytics-metric-grid">
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Jobs analyzed</div>
          <div className="analytics-metric-value">{formatCompactNumber(languageData.jobs_considered)}</div>
          <div className="muted">{languageData.date_start || '-'} to {languageData.date_end || '-'}</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Language mentions</div>
          <div className="analytics-metric-value">{formatCompactNumber(languageData.language_mentions)}</div>
          <div className="muted">{formatCompactNumber(languageData.unique_language_count)} distinct languages in scope</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Fastest mover</div>
          <div className="analytics-metric-value">{topLanguageCards[0]?.language || '-'}</div>
          <div className="muted">{topLanguageCards[0] ? `${formatSignedPercent(topLanguageCards[0].momentum_pct)} vs prior 30 days` : 'No data'}</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Geo coverage risk</div>
          <div className="analytics-metric-value">{Number(languageData.geo_coverage?.other_region_share_pct || 0).toFixed(1)}%</div>
          <div className="muted">Share still mapped to Other region</div>
        </div>
      </div>

      <div className="card analytics-language-card">
        <div className="card-head">
          <div>
            <div className="analytics-section-title">90-day trend lines</div>
            <div className="muted">The chart highlights the languages with the strongest recent hiring footprint in the local dataset.</div>
          </div>
          <div className="row-actions-right muted">Generated {String(languageData.generated_at || '').slice(0, 19).replace('T', ' ') || '-'}</div>
        </div>
        <LanguageTrendChart trend={languageData} t={t} />
      </div>

      <div className="analytics-language-card-grid">
        {topLanguageCards.map((item) => (
          <div key={item.language} className="analytics-language-card">
            <div className="analytics-language-card-head">
              <div>
                <div className="analytics-language-name">{item.language}</div>
                <div className="muted">{item.jobs} mentions | {item.share_pct}% of top-language volume</div>
              </div>
              <span className={`inline-badge ${item.trend_direction === 'down' ? 'inline-badge-warn' : ''}`}>
                {formatSignedPercent(item.momentum_pct)}
              </span>
            </div>
            <div className="analytics-language-stat-row">
              <span>Dominant region</span>
              <b>{item.dominant_region || 'Other'}</b>
            </div>
            <div className="analytics-language-stat-row">
              <span>Region share</span>
              <b>{Number(item.dominant_region_share_pct || 0).toFixed(1)}%</b>
            </div>
            <div className="analytics-language-stat-row">
              <span>Region spread</span>
              <b>{item.region_spread || 0} regions</b>
            </div>
            <div className="analytics-language-actions">
              <button onClick={() => onOpenLanguageJobs(item.language)}>Open jobs</button>
            </div>
          </div>
        ))}
      </div>

      <div className="card analytics-language-card">
        <div className="card-head">
          <div>
            <div className="analytics-section-title">Regional concentration</div>
            <div className="muted">Each language keeps its own regional split, so this avoids flattening everything into one global country table.</div>
          </div>
        </div>
        <div className="analytics-region-grid">
          {regionBreakdown.map((item) => (
            <div key={item.language} className="analytics-region-card">
              <div className="analytics-region-title">{item.language}</div>
              {(item.regions || []).slice(0, 4).map((region) => (
                <div key={`${item.language}-${region.region}`} className="analytics-region-row">
                  <div className="analytics-region-meta">
                    <span>{region.region}</span>
                    <span className="muted">{region.jobs} mentions</span>
                  </div>
                  <div className="analytics-region-bar-shell">
                    <div className="analytics-region-bar-fill" style={{ width: `${Math.min(100, Number(region.share_pct || 0))}%` }} />
                  </div>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => onOpenLanguageJobs(item.language, (region.countries || []).map((countryItem) => countryItem.country))}
                  >
                    {(region.countries || []).map((countryItem) => countryItem.country).filter(Boolean).slice(0, 2).join(', ') || 'Open jobs'}
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="analytics-context-grid">
        <div className="card analytics-language-card">
          <div className="card-head">
            <div>
              <div className="analytics-section-title">Why this trend is moving</div>
              <div className="muted">External context loads separately, reuses cached results when available, and refreshes stale sources in the background so the chart stays fast.</div>
            </div>
            {languageContextLoading ? <span className="muted">Loading market context...</span> : null}
          </div>
          {languageContextError ? <div className="error-text">{languageContextError}</div> : null}
          {macroCards.length > 0 ? (
            <div className="analytics-macro-grid">
              {macroCards.map((item) => (
                <div key={item.title} className="analytics-macro-card">
                  <div className="analytics-macro-title">{item.title}</div>
                  <div className="analytics-macro-body">{item.body}</div>
                </div>
              ))}
            </div>
          ) : null}
          <div className="analytics-context-list">
            {contextItems.map((item) => (
              <div key={item.language} className="analytics-context-card">
                <div className="analytics-context-title">{item.language}: {item.headline}</div>
                <div className="analytics-context-story">{item.regional_story}</div>
                <ul className="prediction-list">
                  {(item.local_reasons || []).map((reason, index) => (
                    <li key={`${item.language}-local-${index}`}>{reason}</li>
                  ))}
                </ul>
                {Array.isArray(item.external_reasons) && item.external_reasons.length > 0 ? (
                  <>
                    <div className="analytics-context-subtitle">External context</div>
                    <ul className="prediction-list">
                      {item.external_reasons.map((reason, index) => (
                        <li key={`${item.language}-external-${index}`}>{reason}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="card analytics-language-card">
          <div className="card-head">
            <div>
              <div className="analytics-section-title">Qwen lens</div>
              <div className="muted">Nightly Qwen snapshots expand the trend into macro hypotheses, crawl targets, and what would change the view without rerunning the model on every page open.</div>
            </div>
            <div className="row-actions-right muted">
              {languageAiLoading ? <span>Loading cached lens...</span> : null}
              {typeof onRefreshLanguageAiInsights === 'function' ? <button type="button" onClick={onRefreshLanguageAiInsights}>Reload snapshot</button> : null}
            </div>
          </div>
          {languageAiError ? <div className="error-text">{languageAiError}</div> : null}
          {languageAiInsights ? (
            <div className="analytics-context-list">
              <div className="analytics-context-card">
                <div className="analytics-context-title">{languageAiInsights.thesis}</div>
                <div className="analytics-context-story">
                  Confidence {Number(languageAiInsights.confidence || 0).toFixed(2)} | {languageAiInsights.model || 'local model'} | {languageAiInsights.cache_state || 'fresh'}
                </div>
                <div className="analytics-context-subtitle">Macro dimensions</div>
                <ul className="prediction-list">
                  {(languageAiInsights.dimension_notes || []).map((note, index) => (
                    <li key={`language-dimension-${index}`}>
                      <b>{note.dimension}</b>: {note.reading} {note.evidence_basis ? `(${note.evidence_basis})` : ''}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analytics-context-card">
                <div className="analytics-context-title">Crawl expansion plan</div>
                <ul className="prediction-list">
                  {(languageAiInsights.crawl_expansions || []).map((item, index) => (
                    <li key={`language-crawl-${index}`}>
                      <b>{item.priority}</b> {item.target}: {item.question} {item.why_it_matters ? `- ${item.why_it_matters}` : ''}
                    </li>
                  ))}
                </ul>
                <div className="analytics-context-subtitle">What would change the view</div>
                <ul className="prediction-list">
                  {(languageAiInsights.what_would_change_view || []).map((item, index) => (
                    <li key={`language-change-${index}`}>{item}</li>
                  ))}
                </ul>
                {(languageAiInsights.limitations || []).length > 0 ? (
                  <>
                    <div className="analytics-context-subtitle">Limits</div>
                    <ul className="prediction-list">
                      {(languageAiInsights.limitations || []).map((item, index) => (
                        <li key={`language-limit-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="muted">{languageAiLoading ? 'Loading cached lens...' : 'Qwen insight is ready after the nightly snapshot has been materialized.'}</div>
          )}
        </div>

        <div className="card analytics-language-card">
          <div className="card-head">
            <div>
              <div className="analytics-section-title">Sources</div>
              <div className="muted">Lightweight external crawl, no JS rendering, pulled only from a short curated list to keep the request bounded.</div>
            </div>
          </div>
          <div className="analytics-source-list">
            {(languageContext?.sources || []).map((source) => (
              <div key={source.id} className="analytics-source-card">
                <div className="analytics-source-head">
                  <a href={source.url} target="_blank" rel="noreferrer">{source.publisher}: {source.title}</a>
                  <span className={`inline-badge ${source.status !== 'ok' ? 'inline-badge-warn' : ''}`}>{source.status}</span>
                </div>
                <div className="muted">Fetched in {source.duration_ms}ms</div>
                {Array.isArray(source.facts) && source.facts.length > 0 ? (
                  <ul className="prediction-list">
                    {source.facts.map((fact, index) => (
                      <li key={`${source.id}-${index}`}>{fact.text}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="muted">{source.error || 'No structured fact extracted.'}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
