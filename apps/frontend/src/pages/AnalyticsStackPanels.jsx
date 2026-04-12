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

const STACK_TREND_COLORS = ['#1455a1', '#0d6c5f', '#cc5f16', '#8b2f8f', '#b42318', '#0f766e', '#6b46c1', '#475467']

function linePathFromPoints(points) {
  if (!Array.isArray(points) || points.length === 0) return ''
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
}

function StackTrendChart({ trend, t }) {
  const series = Array.isArray(trend?.daily_series) ? trend.daily_series : []
  const topGroups = Array.isArray(trend?.top_groups) ? trend.top_groups : []
  if (!series.length || !topGroups.length) return null
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
    ...series.flatMap((point) => topGroups.map((item) => Number(point?.groups?.[item.group] || 0))),
  )
  const axisTicks = [0, 0.25, 0.5, 0.75, 1]
  const lines = topGroups.map((item, index) => {
    const color = STACK_TREND_COLORS[index % STACK_TREND_COLORS.length]
    const points = series.map((point, pointIndex) => {
      const count = Number(point?.groups?.[item.group] || 0)
      const x = padLeft + (pointIndex / Math.max(1, series.length - 1)) * innerWidth
      const y = padTop + innerHeight - (count / maxY) * innerHeight
      return { x, y, count }
    })
    return { group: item.group, color, points }
  })
  return (
    <div className="language-trend-chart-wrap">
      <div className="language-trend-legend">
        {topGroups.map((item, index) => (
          <span key={item.group}>
            <i className="legend-dot" style={{ background: STACK_TREND_COLORS[index % STACK_TREND_COLORS.length] }} />
            {item.group}
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
            <path key={line.group} d={linePathFromPoints(line.points)} className="chart-line" style={{ stroke: line.color }} />
          ))}
          {lines.map((line) => (
            line.points.filter((_, index) => index === line.points.length - 1).map((point) => (
              <g key={`${line.group}-last`}>
                <circle cx={point.x} cy={point.y} r="4" style={{ fill: line.color, stroke: '#fff', strokeWidth: 2 }} />
                <text x={point.x + 8} y={point.y - 8} className="chart-axis-text">{line.group}</text>
              </g>
            ))
          ))}
        </svg>
      </div>
      <div className="applied-chart-hint muted">
        90-day local demand based on recent first-seen jobs. Counts represent stack group mentions per day, not unique developers.
      </div>
    </div>
  )
}

export function AnalyticsStackPanels({
  stackData,
  stackContext,
  stackContextLoading,
  stackContextError,
  stackAiInsights,
  stackAiLoading,
  stackAiError,
  onOpenStackJobs,
  onRefreshStackAiInsights,
  t,
}) {
  const topStackCards = Array.isArray(stackData?.top_groups) ? stackData.top_groups : []
  const regionBreakdown = Array.isArray(stackData?.region_breakdown) ? stackData.region_breakdown : []
  const macroCards = Array.isArray(stackContext?.macro_cards) ? stackContext.macro_cards : []
  const contextItems = Array.isArray(stackContext?.items) ? stackContext.items : []
  const crawlRecommendations = Array.isArray(stackData?.crawl_recommendations) ? stackData.crawl_recommendations : []

  return (
    <>
      <div className="analytics-metric-grid">
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Jobs analyzed</div>
          <div className="analytics-metric-value">{formatCompactNumber(stackData.jobs_considered)}</div>
          <div className="muted">{stackData.date_start || '-'} to {stackData.date_end || '-'}</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Group mentions</div>
          <div className="analytics-metric-value">{formatCompactNumber(stackData.group_mentions)}</div>
          <div className="muted">{formatCompactNumber(stackData.unique_group_count)} distinct groups in scope</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Fastest mover</div>
          <div className="analytics-metric-value">{topStackCards[0]?.group || '-'}</div>
          <div className="muted">{topStackCards[0] ? `${formatSignedPercent(topStackCards[0].momentum_pct)} vs prior 30 days` : 'No data'}</div>
        </div>
        <div className="analytics-metric-card">
          <div className="analytics-metric-label">Coverage risk</div>
          <div className="analytics-metric-value">{Number(stackData.geo_coverage?.other_group_share_pct || 0).toFixed(1)}%</div>
          <div className="muted">Share still mapped to Other</div>
        </div>
      </div>

      <div className="card analytics-language-card">
        <div className="card-head">
          <div>
            <div className="analytics-section-title">90-day trend lines</div>
            <div className="muted">The chart highlights the stack groups with the strongest recent hiring footprint in the local dataset.</div>
          </div>
          <div className="row-actions-right muted">Generated {String(stackData.generated_at || '').slice(0, 19).replace('T', ' ') || '-'}</div>
        </div>
        <StackTrendChart trend={stackData} t={t} />
      </div>

      <div className="analytics-language-card-grid">
        {topStackCards.map((item) => (
          <div key={item.group} className="analytics-language-card">
            <div className="analytics-language-card-head">
              <div>
                <div className="analytics-language-name">{item.group}</div>
                <div className="muted">{item.jobs} mentions | {item.share_pct}% of top-group volume</div>
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
              <span>Signal mix</span>
              <b>{(Array.isArray(item.signal_mix_samples) ? item.signal_mix_samples[0] : '') || '-'}</b>
            </div>
            <div className="analytics-language-actions">
              <button onClick={() => onOpenStackJobs(item.group)}>Open jobs</button>
            </div>
          </div>
        ))}
      </div>

      <div className="card analytics-language-card">
        <div className="card-head">
          <div>
            <div className="analytics-section-title">Regional concentration</div>
            <div className="muted">Each stack group keeps its own regional split so the analysis stays specific instead of flattening everything into one country table.</div>
          </div>
        </div>
        <div className="analytics-region-grid">
          {regionBreakdown.map((item) => (
            <div key={item.group} className="analytics-region-card">
              <div className="analytics-region-title">{item.group}</div>
              {(item.regions || []).slice(0, 4).map((region) => (
                <div key={`${item.group}-${region.region}`} className="analytics-region-row">
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
                    onClick={() => onOpenStackJobs(item.group, (region.countries || []).map((countryItem) => countryItem.country))}
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
              <div className="muted">External context stays separate, reuses cached results when available, and refreshes stale sources in the background so the chart remains fast.</div>
            </div>
            {stackContextLoading ? <span className="muted">Loading market context...</span> : null}
          </div>
          {stackContextError ? <div className="error-text">{stackContextError}</div> : null}
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
              <div key={item.group} className="analytics-context-card">
                <div className="analytics-context-title">{item.group}: {item.headline}</div>
                <div className="analytics-context-story">{item.regional_story}</div>
                <ul className="prediction-list">
                  {(item.local_reasons || []).map((reason, index) => (
                    <li key={`${item.group}-local-${index}`}>{reason}</li>
                  ))}
                </ul>
                {Array.isArray(item.external_reasons) && item.external_reasons.length > 0 ? (
                  <>
                    <div className="analytics-context-subtitle">External context</div>
                    <ul className="prediction-list">
                      {item.external_reasons.map((reason, index) => (
                        <li key={`${item.group}-external-${index}`}>{reason}</li>
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
              <div className="muted">Nightly Qwen snapshots expand the stack trend into macro hypotheses, crawl targets, and what would change the view without rerunning the model on every page open.</div>
            </div>
            <div className="row-actions-right muted">
              {stackAiLoading ? <span>Loading cached lens...</span> : null}
              {typeof onRefreshStackAiInsights === 'function' ? <button type="button" onClick={onRefreshStackAiInsights}>Reload snapshot</button> : null}
            </div>
          </div>
          {stackAiError ? <div className="error-text">{stackAiError}</div> : null}
          {stackAiInsights ? (
            <div className="analytics-context-list">
              <div className="analytics-context-card">
                <div className="analytics-context-title">{stackAiInsights.thesis}</div>
                <div className="analytics-context-story">
                  Confidence {Number(stackAiInsights.confidence || 0).toFixed(2)} | {stackAiInsights.model || 'local model'} | {stackAiInsights.cache_state || 'fresh'}
                </div>
                <div className="analytics-context-subtitle">Macro dimensions</div>
                <ul className="prediction-list">
                  {(stackAiInsights.dimension_notes || []).map((note, index) => (
                    <li key={`stack-dimension-${index}`}>
                      <b>{note.dimension}</b>: {note.reading} {note.evidence_basis ? `(${note.evidence_basis})` : ''}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="analytics-context-card">
                <div className="analytics-context-title">Crawl expansion plan</div>
                <ul className="prediction-list">
                  {(stackAiInsights.crawl_expansions || []).map((item, index) => (
                    <li key={`stack-crawl-${index}`}>
                      <b>{item.priority}</b> {item.target}: {item.question} {item.why_it_matters ? `- ${item.why_it_matters}` : ''}
                    </li>
                  ))}
                </ul>
                <div className="analytics-context-subtitle">What would change the view</div>
                <ul className="prediction-list">
                  {(stackAiInsights.what_would_change_view || []).map((item, index) => (
                    <li key={`stack-change-${index}`}>{item}</li>
                  ))}
                </ul>
                {(stackAiInsights.limitations || []).length > 0 ? (
                  <>
                    <div className="analytics-context-subtitle">Limits</div>
                    <ul className="prediction-list">
                      {(stackAiInsights.limitations || []).map((item, index) => (
                        <li key={`stack-limit-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="muted">{stackAiLoading ? 'Loading cached lens...' : 'Qwen insight is ready after the nightly snapshot has been materialized.'}</div>
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
            {(stackContext?.sources || []).map((source) => (
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

      {crawlRecommendations.length > 0 ? (
        <div className="card analytics-language-card">
          <div className="card-head">
            <div>
              <div className="analytics-section-title">Buckets that still need more crawl</div>
              <div className="muted">These groups are still thin enough that extra backfill or crawl will make the trend less noisy.</div>
            </div>
          </div>
          <div className="analytics-source-list">
            {crawlRecommendations.map((item) => (
              <div key={item.group} className="analytics-source-card">
                <div className="analytics-source-head">
                  <span>{item.group}</span>
                  <span className="inline-badge inline-badge-warn">{item.jobs} samples</span>
                </div>
                <div className="muted">{item.reason}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  )
}
