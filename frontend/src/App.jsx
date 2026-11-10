import { useEffect, useMemo, useState } from "react";

import {
  fetchAlerts,
  fetchAlertStatus,
  fetchOpportunities,
  fetchSettings,
  fetchSpreadHistory,
  fetchStatus,
  fetchTelegramStatus
} from "./api.js";
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatUsd
} from "./formatters.js";

function App() {
  const [opportunities, setOpportunities] = useState([]);
  const [opportunityMeta, setOpportunityMeta] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [alertStatus, setAlertStatus] = useState(null);
  const [telegramStatus, setTelegramStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [scannerStatus, setScannerStatus] = useState(null);
  const [defaultFilters, setDefaultFilters] = useState(createEmptyFilters());
  const [draftFilters, setDraftFilters] = useState(createEmptyFilters());
  const [appliedFilters, setAppliedFilters] = useState(null);
  const [requestStatus, setRequestStatus] = useState("loading");
  const [error, setError] = useState("");
  const [historySelection, setHistorySelection] = useState(null);

  useEffect(() => {
    let isMounted = true;

    async function loadSettings() {
      setRequestStatus("loading");
      setError("");

      try {
        const loadedSettings = await fetchSettings();
        const loadedDefaults = toUiFilters(loadedSettings.default_filters);

        if (isMounted) {
          setSettings(loadedSettings);
          setDefaultFilters(loadedDefaults);
          setDraftFilters(loadedDefaults);
          setAppliedFilters(loadedDefaults);
        }
      } catch (loadError) {
        if (isMounted) {
          setError(loadError.message);
          setRequestStatus("error");
        }
      }
    }

    loadSettings();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!appliedFilters) {
      return undefined;
    }

    let isMounted = true;

    async function loadLiveData(showLoading) {
      if (showLoading) {
        setRequestStatus("loading");
      }
      setError("");

      try {
        const [
          loadedOpportunities,
          loadedScannerStatus,
          loadedAlerts,
          loadedAlertStatus,
          loadedTelegramStatus
        ] = await Promise.all([
          fetchOpportunities(appliedFilters),
          fetchStatus(),
          fetchAlerts(),
          fetchAlertStatus(),
          fetchTelegramStatus()
        ]);
        if (isMounted) {
          setOpportunities(loadedOpportunities.opportunities ?? []);
          setOpportunityMeta(loadedOpportunities);
          setAlerts(loadedAlerts.alerts ?? []);
          setAlertStatus(loadedAlertStatus);
          setTelegramStatus(loadedTelegramStatus);
          setScannerStatus(loadedScannerStatus);
          setRequestStatus("ready");
        }
      } catch (loadError) {
        if (isMounted) {
          setError(loadError.message);
          setRequestStatus("error");
        }
      }
    }

    loadLiveData(true);
    const refreshTimer = window.setInterval(() => {
      loadLiveData(false);
    }, 5000);

    return () => {
      isMounted = false;
      window.clearInterval(refreshTimer);
    };
  }, [appliedFilters]);

  const lastUpdated = useMemo(() => {
    if (!scannerStatus?.last_updated) {
      return "-";
    }

    return formatDateTime(scannerStatus.last_updated);
  }, [scannerStatus]);

  const visibleExchangeOptions = useMemo(
    () => getVisibleExchangeOptions(scannerStatus, settings, opportunities),
    [scannerStatus, settings, opportunities]
  );
  const activeExchangeOptions = useMemo(
    () => getActiveExchangeOptions(scannerStatus, settings, opportunities),
    [scannerStatus, settings, opportunities]
  );
  const totalOpportunities = scannerStatus?.total_opportunity_count
    ?? scannerStatus?.opportunity_count
    ?? opportunities.length;
  const totalStoredOpportunities = opportunityMeta?.total_stored_opportunity_count
    ?? totalOpportunities;
  const filteredOpportunityCount = opportunityMeta?.filtered_opportunity_count
    ?? opportunities.length;
  const returnedOpportunityCount = opportunityMeta?.returned_count
    ?? opportunities.length;

  function applyFilters() {
    const normalizedFilters = normalizeFilters(draftFilters);
    setDraftFilters(normalizedFilters);
    setAppliedFilters(normalizedFilters);
  }

  function resetFilters() {
    const restoredFilters = normalizeFilters(defaultFilters);
    setDraftFilters(restoredFilters);
    setAppliedFilters(restoredFilters);
  }

  function showAllOpportunities() {
    const exchangeSelection = activeExchangeOptions.length
      ? activeExchangeOptions
      : visibleExchangeOptions;
    const showAllFilters = {
      minRawSpread: "0",
      minNetSpread: "-1",
      minVolume24hUsd: "0",
      symbolQuery: "",
      sortBy: draftFilters.sortBy || "net_spread",
      sortDir: draftFilters.sortDir || "desc",
      limit: draftFilters.limit || "100",
      exchanges: exchangeSelection
    };

    setDraftFilters(showAllFilters);
    setAppliedFilters(showAllFilters);
  }

  if (historySelection) {
    return (
      <main className="app-shell">
        <header className="top-bar">
          <div>
            <p className="eyebrow">SigmaScanner history</p>
            <h1 className="history-title">{historySelection.symbol} - {historySelection.longExchange} vs {historySelection.shortExchange}</h1>
          </div>
          <button
            type="button"
            className="secondary-button standalone-action"
            onClick={() => setHistorySelection(null)}
          >
            Back
          </button>
        </header>

        <SpreadHistoryView selection={historySelection} />
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Perpetual futures arbitrage</p>
          <h1 className="brand-title">SigmaScanner</h1>
        </div>
        <div className="top-status-group">
          <div className="status-panel">
            <span className={`status-dot status-${requestStatus}`} aria-hidden="true" />
            <span>{requestStatus === "ready" ? formatModeLabel(scannerStatus?.mode) : requestStatus}</span>
          </div>
          <div className="compact-status-chips" aria-label="Alerts and Telegram status">
            <span className="compact-status-chip">
              <span>Alerts</span>
              <strong>{formatAlertStatusLabel(alertStatus)} / {alertStatus?.active_alert_count ?? 0}</strong>
            </span>
            <span className={`compact-status-chip ${telegramStatus?.last_error ? "chip-error" : ""}`}>
              <span>Telegram</span>
              <strong>{formatTelegramStatusLabel(telegramStatus)} / {telegramStatus?.sent_count ?? 0}</strong>
            </span>
          </div>
        </div>
      </header>

      <section className="metrics-band" aria-label="Scanner summary">
        <div>
          <span className="metric-label">Mode</span>
          <strong>{formatModeLabel(scannerStatus?.mode)}</strong>
        </div>
        <div>
          <span className="metric-label">Market data</span>
          <strong>{formatMarketDataMode(scannerStatus?.market_data_mode)}</strong>
        </div>
        <div>
          <span className="metric-label">WebSocket</span>
          <strong>{formatWebSocketStatus(scannerStatus)}</strong>
        </div>
        <div>
          <span className="metric-label">Symbol mode</span>
          <strong>{formatSymbolSelectionMode(scannerStatus?.symbol_selection_mode)}</strong>
        </div>
        <div>
          <span className="metric-label">Selected symbols</span>
          <strong>{scannerStatus?.selected_symbol_count ?? "-"}</strong>
        </div>
        <div>
          <span className="metric-label">Snapshots</span>
          <strong>{scannerStatus?.snapshot_count ?? "-"}</strong>
        </div>
        <div>
          <span className="metric-label">Scanner found</span>
          <strong>{totalStoredOpportunities}</strong>
        </div>
        <div>
          <span className="metric-label">Matching filters</span>
          <strong>{filteredOpportunityCount}</strong>
        </div>
        <div>
          <span className="metric-label">Displayed rows</span>
          <strong>{returnedOpportunityCount}</strong>
        </div>
        <div>
          <span className="metric-label">Last update</span>
          <strong>{lastUpdated}</strong>
        </div>
        <div>
          <span className="metric-label">Connectors</span>
          <strong>{formatConnectors(scannerStatus?.active_connectors)}</strong>
        </div>
      </section>

      <FilterControls
        filters={draftFilters}
        exchangeOptions={visibleExchangeOptions}
        onChange={setDraftFilters}
        onApply={applyFilters}
        onReset={resetFilters}
        onShowAll={showAllOpportunities}
        disabled={!settings}
      />

      {scannerStatus?.last_error && (
        <p className="warning-message">Scanner degraded: {scannerStatus.last_error}</p>
      )}

      {requestStatus === "error" ? (
        <p className="error-message">{error}</p>
      ) : (
        <OpportunitiesTable
          opportunities={opportunities}
          status={requestStatus}
          totalOpportunities={totalStoredOpportunities}
          filteredOpportunities={filteredOpportunityCount}
          onOpenHistory={setHistorySelection}
        />
      )}
    </main>
  );
}

function AlertsPanel({ alertStatus, telegramStatus, alerts }) {
  const visibleAlerts = Array.isArray(alerts) ? alerts.slice(0, 5) : [];

  return (
    <section className="alerts-panel" aria-label="Alert engine">
      <div className="alerts-heading">
        <div>
          <span className="metric-label">Alert engine</span>
          <strong>{formatAlertStatusLabel(alertStatus)}</strong>
        </div>
        <div>
          <span className="metric-label">Active</span>
          <strong>{alertStatus?.active_alert_count ?? 0}</strong>
        </div>
        <div>
          <span className="metric-label">Suppressed</span>
          <strong>{alertStatus?.suppressed_count ?? 0}</strong>
        </div>
        <div>
          <span className="metric-label">Telegram</span>
          <strong>{formatTelegramStatusLabel(telegramStatus)}</strong>
        </div>
        <div>
          <span className="metric-label">Sent</span>
          <strong>{telegramStatus?.sent_count ?? 0}</strong>
        </div>
        <div>
          <span className="metric-label">Tracked</span>
          <strong>{telegramStatus?.tracked_alert_keys_count ?? "-"}</strong>
        </div>
      </div>
      {telegramStatus?.last_error && (
        <p className="telegram-error">Telegram: {telegramStatus.last_error}</p>
      )}
      {visibleAlerts.length > 0 ? (
        <div className="alerts-list">
          {visibleAlerts.map((alert) => (
            <div className="alert-row" key={alert.id}>
              <div>
                <strong>{alert.symbol}</strong>
                <span>{alert.long_exchange} / {alert.short_exchange}</span>
              </div>
              <span className={`pill severity-${alert.severity.toLowerCase()}`}>
                {alert.severity}
              </span>
              <span>Net {formatPercent(alert.estimated_net_spread_percent)}</span>
              <span>Depth {formatOptionalPercent(alert.depth_adjusted_net_spread_percent)}</span>
              <span>Score {formatNumber(alert.alert_score, 2)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="alerts-empty">No active alert candidates.</p>
      )}
    </section>
  );
}

function FilterControls({
  filters,
  exchangeOptions,
  onChange,
  onApply,
  onReset,
  onShowAll,
  disabled
}) {
  function updateFilter(key, value) {
    onChange((currentFilters) => ({
      ...currentFilters,
      [key]: value
    }));
  }

  function toggleExchange(exchange) {
    onChange((currentFilters) => {
      const currentExchanges = new Set(currentFilters.exchanges);
      if (currentExchanges.has(exchange)) {
        currentExchanges.delete(exchange);
      } else {
        currentExchanges.add(exchange);
      }

      return {
        ...currentFilters,
        exchanges: Array.from(currentExchanges)
      };
    });
  }

  return (
    <section className="filter-bar" aria-label="Opportunity filters">
      <label>
        <span>Min raw spread</span>
        <input
          type="text"
          inputMode="decimal"
          value={filters.minRawSpread}
          onChange={(event) => updateFilter("minRawSpread", event.target.value)}
          placeholder="0.10"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Min net spread</span>
        <input
          type="text"
          inputMode="decimal"
          value={filters.minNetSpread}
          onChange={(event) => updateFilter("minNetSpread", event.target.value)}
          placeholder="0.00"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Min 24h volume</span>
        <input
          type="text"
          inputMode="decimal"
          value={filters.minVolume24hUsd}
          onChange={(event) => updateFilter("minVolume24hUsd", event.target.value)}
          placeholder="400000"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Symbol search</span>
        <input
          type="text"
          value={filters.symbolQuery}
          onChange={(event) => updateFilter("symbolQuery", event.target.value)}
          placeholder="SOL"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Sort by</span>
        <select
          value={filters.sortBy}
          onChange={(event) => updateFilter("sortBy", event.target.value)}
          disabled={disabled}
        >
          <option value="net_spread">Net spread</option>
          <option value="raw_spread">Raw spread</option>
          <option value="volume_24h">24h volume</option>
          <option value="symbol">Symbol</option>
          <option value="updated_at">Updated</option>
        </select>
      </label>
      <label>
        <span>Direction</span>
        <select
          value={filters.sortDir}
          onChange={(event) => updateFilter("sortDir", event.target.value)}
          disabled={disabled}
        >
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </label>
      <label>
        <span>Limit</span>
        <select
          value={filters.limit}
          onChange={(event) => updateFilter("limit", event.target.value)}
          disabled={disabled}
        >
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100">100</option>
          <option value="250">250</option>
        </select>
      </label>
      <fieldset className="exchange-filter">
        <legend>Exchanges</legend>
        <div className="exchange-options">
          {exchangeOptions.map((exchange) => (
            <label key={exchange} className="exchange-option">
              <input
                type="checkbox"
                checked={filters.exchanges.includes(exchange)}
                onChange={() => toggleExchange(exchange)}
                disabled={disabled}
              />
              <span>{exchange}</span>
            </label>
          ))}
          {!exchangeOptions.length && (
            <span className="exchange-empty">No active exchanges</span>
          )}
        </div>
      </fieldset>
      <div className="filter-actions">
        <button type="button" onClick={onApply} disabled={disabled}>
          Apply filters
        </button>
        <button type="button" className="secondary-button" onClick={onShowAll} disabled={disabled}>
          Show all
        </button>
        <button type="button" className="secondary-button" onClick={onReset} disabled={disabled}>
          Reset filters
        </button>
      </div>
    </section>
  );
}

function OpportunitiesTable({
  opportunities,
  status,
  totalOpportunities,
  filteredOpportunities,
  onOpenHistory
}) {
  const emptyMessage =
    status === "loading"
      ? "Loading opportunities..."
      : createEmptyOpportunityMessage(totalOpportunities, filteredOpportunities);
  const hasDepthData = opportunities.some((opportunity) => opportunity.depth_check);

  return (
    <section className="table-section" aria-label="Arbitrage opportunities">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Pair</th>
              <th className="history-column">History</th>
              <th>Long / Buy</th>
              <th>Short / Sell</th>
              <th>Ask</th>
              <th>Bid</th>
              <th>Raw spread</th>
              <th>Net spread</th>
              <th>Fees</th>
              <th>24h volume</th>
              <th>Size</th>
              <th>Funding</th>
              <th>Liquidity</th>
              {hasDepthData && <th>Depth</th>}
            </tr>
          </thead>
          <tbody>
            {opportunities.map((opportunity) => (
              <tr key={`${opportunity.symbol}-${opportunity.long_exchange}-${opportunity.short_exchange}`}>
                <td className="symbol-cell">{opportunity.symbol}</td>
                <td className="history-cell">
                  <button
                    type="button"
                    className="history-chip"
                    onClick={() => onOpenHistory({
                      symbol: opportunity.symbol,
                      longExchange: opportunity.long_exchange,
                      shortExchange: opportunity.short_exchange
                    })}
                  >
                    Open
                  </button>
                </td>
                <td>{opportunity.long_exchange}</td>
                <td>{opportunity.short_exchange}</td>
                <td>{formatUsd(opportunity.ask_price, 4)}</td>
                <td>{formatUsd(opportunity.bid_price, 4)}</td>
                <td className="positive">{formatPercent(opportunity.raw_spread_percent)}</td>
                <td className={opportunity.estimated_net_spread_percent >= 0 ? "positive" : "negative"}>
                  {formatPercent(opportunity.estimated_net_spread_percent)}
                </td>
                <td>{formatPercent(opportunity.estimated_fee_percent)}</td>
                <td>{formatUsd(opportunity.volume_24h_usd, 0)}</td>
                <td>
                  {formatNumber(opportunity.best_ask_size, 4)} / {formatNumber(opportunity.best_bid_size, 4)}
                </td>
                <td>
                  <span className={`pill funding-${opportunity.funding_impact.toLowerCase()}`}>
                    {opportunity.funding_impact}
                  </span>
                </td>
                <td>
                  <span className={`pill liquidity-${opportunity.liquidity_status.toLowerCase()}`}>
                    {opportunity.liquidity_status}
                  </span>
                </td>
                {hasDepthData && (
                  <td>
                    {opportunity.depth_check ? (
                      <DepthCheckCell depthCheck={opportunity.depth_check} />
                    ) : (
                      "-"
                    )}
                  </td>
                )}
              </tr>
            ))}
            {!opportunities.length && (
              <tr>
                <td colSpan={hasDepthData ? 14 : 13} className="empty-state">
                  {emptyMessage}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SpreadHistoryView({ selection }) {
  const [history, setHistory] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [interval, setInterval] = useState("raw");

  useEffect(() => {
    let isMounted = true;

    async function loadHistory() {
      setStatus("loading");
      setError("");

      try {
        const loadedHistory = await fetchSpreadHistory({
          symbol: selection.symbol,
          longExchange: selection.longExchange,
          shortExchange: selection.shortExchange,
          interval,
          limit: 500
        });
        if (isMounted) {
          setHistory(loadedHistory);
          setStatus("ready");
        }
      } catch (loadError) {
        if (isMounted) {
          setError(loadError.message);
          setStatus("error");
        }
      }
    }

    loadHistory();

    return () => {
      isMounted = false;
    };
  }, [selection, interval]);

  const rows = Array.isArray(history?.rows) ? history.rows : [];
  const stats = useMemo(() => normalizeHistoryStats(history?.stats, rows), [history, rows]);
  const statsItems = useMemo(() => createHistoryStatsItems(stats), [stats]);

  return (
    <section className="history-screen" aria-label="Spread history">
      <div className="history-toolbar">
        <div>
          <p className="history-kicker">Spread analytics</p>
          <h2>{selection.symbol}</h2>
          <p>{selection.longExchange} long / {selection.shortExchange} short</p>
        </div>
        <div className="interval-selector" aria-label="History interval">
          {HISTORY_INTERVALS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={interval === option.value ? "active" : ""}
              onClick={() => setInterval(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="history-stats-grid" aria-label="History statistics">
        {statsItems.map((item) => (
          <div key={item.label} className="history-stat-card">
            <span className="metric-label">{item.label}</span>
            <strong>{item.value}</strong>
            {item.detail && <small>{item.detail}</small>}
          </div>
        ))}
      </div>

      <div className="history-explainer">
        <span><i className="legend-swatch upper" /> Upper line</span>
        <span><i className="legend-swatch lower" /> Lower line</span>
        <p>Distance between the two lines is the total spread. 0% means prices converged.</p>
      </div>

      {status === "loading" && (
        <p className="empty-state history-message">Loading spread history...</p>
      )}
      {status === "error" && (
        <p className="error-message">{error}</p>
      )}
      {status === "ready" && rows.length === 0 && (
        <p className="empty-state history-message">
          No history stored for this exact symbol, long exchange, and short exchange yet. Samples appear after the scanner records this direction.
        </p>
      )}
      {status === "ready" && rows.length > 0 && (
        <>
          <SpreadHistoryChart rows={rows} stats={stats} />
          <div className="history-footer">
            <span>Interval {history?.interval ?? interval}</span>
            <span>Returned {history?.returned_count ?? rows.length} rows</span>
            <span>Raw samples {formatNumber(stats.sampleCount, 0)}</span>
          </div>
        </>
      )}
    </section>
  );
}

function SpreadHistoryChart({ rows, stats }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const width = 920;
  const height = 410;
  const padding = {
    top: 28,
    right: 36,
    bottom: 58,
    left: 72
  };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const maxAbsValue = Math.max(
    0.01,
    ...rows.flatMap((row) => [
      Math.abs(Number(row.lower_line_percent) || 0),
      Math.abs(Number(row.upper_line_percent) || 0),
      Math.abs(Number(row.selected_spread_percent) || 0)
    ])
  );
  const yExtent = createChartExtent(maxAbsValue);
  const chart = {
    padding,
    innerWidth,
    innerHeight,
    yExtent
  };
  const lowerPoints = createLinePoints(rows, "lower_line_percent", chart);
  const upperPoints = createLinePoints(rows, "upper_line_percent", chart);
  const chartPointData = rows.map((row, index) => ({
    row,
    ...getChartPoint(rows, index, "upper_line_percent", chart)
  }));
  const zeroY = yToChart(0, padding, innerHeight, yExtent);
  const yTicks = [-yExtent, -yExtent / 2, 0, yExtent / 2, yExtent];
  const xTicks = createChartTickIndexes(rows.length);
  const tooltipPoint = hoverIndex === null ? null : chartPointData[hoverIndex];

  return (
    <div className="history-chart-wrap">
      <div className="history-chart-stage" onMouseLeave={() => setHoverIndex(null)}>
        <svg
          className="history-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Spread history chart with upper, lower, and zero percent lines"
        >
          {yTicks.map((tick) => {
            const y = yToChart(tick, padding, innerHeight, yExtent);
            return (
              <g key={tick}>
                <line
                  x1={padding.left}
                  x2={width - padding.right}
                  y1={y}
                  y2={y}
                  className={tick === 0 ? "chart-zero-line" : "chart-grid-line"}
                />
                <text x={padding.left - 12} y={y + 4} className="chart-label chart-y-label" textAnchor="end">
                  {formatPercent(tick)}
                </text>
              </g>
            );
          })}
          <line
            x1={padding.left}
            x2={padding.left}
            y1={padding.top}
            y2={height - padding.bottom}
            className="chart-axis-line"
          />
          <line
            x1={padding.left}
            x2={width - padding.right}
            y1={height - padding.bottom}
            y2={height - padding.bottom}
            className="chart-axis-line"
          />
          {xTicks.map((index) => {
            const point = chartPointData[index];
            return (
              <g key={index}>
                <line
                  x1={point.x}
                  x2={point.x}
                  y1={padding.top}
                  y2={height - padding.bottom}
                  className="chart-x-grid-line"
                />
                <text x={point.x} y={height - 24} className="chart-label chart-x-label" textAnchor="middle">
                  {formatChartTime(point.row.timestamp)}
                </text>
              </g>
            );
          })}
          <polyline points={upperPoints} className="chart-line chart-line-upper" />
          <polyline points={lowerPoints} className="chart-line chart-line-lower" />
          {chartPointData.map((point, index) => (
            <g key={`${point.row.timestamp}-${index}`}>
              <rect
                x={point.x - Math.max(10, innerWidth / Math.max(rows.length, 1) / 2)}
                y={padding.top}
                width={Math.max(20, innerWidth / Math.max(rows.length, 1))}
                height={innerHeight}
                className="chart-hit-zone"
                onMouseEnter={() => setHoverIndex(index)}
              />
              {hoverIndex === index && (
                <line x1={point.x} x2={point.x} y1={padding.top} y2={height - padding.bottom} className="chart-hover-line" />
              )}
            </g>
          ))}
        </svg>
        {tooltipPoint && (
          <div
            className="history-tooltip"
            style={{
              left: `${(tooltipPoint.x / width) * 100}%`,
              top: `${(tooltipPoint.y / height) * 100}%`
            }}
          >
            <strong>{formatDateTime(tooltipPoint.row.timestamp)}</strong>
            <span>Total spread {formatPercent(getNumber(tooltipPoint.row.selected_spread_percent))}</span>
          </div>
        )}
      </div>
      <div className="history-chart-summary">
        <span>Total spread range {formatNullablePercent(stats.minSpread)} to {formatNullablePercent(stats.maxSpread)}</span>
        <span>0% convergence line is highlighted</span>
      </div>
    </div>
  );
}

function createLinePoints(rows, key, chart) {
  return rows.map((row, index) => {
    const point = getChartPoint(rows, index, key, chart);
    return `${point.x},${point.y}`;
  }).join(" ");
}

function getChartPoint(rows, index, key, chart) {
  const x = rows.length === 1
    ? chart.padding.left + chart.innerWidth / 2
    : chart.padding.left + (index / (rows.length - 1)) * chart.innerWidth;
  const y = yToChart(getNumber(rows[index][key]), chart.padding, chart.innerHeight, chart.yExtent);
  return { x, y };
}

function yToChart(value, padding, innerHeight, yExtent) {
  const ratio = (yExtent - value) / (yExtent * 2);
  return padding.top + ratio * innerHeight;
}

function createChartExtent(maxAbsValue) {
  const padded = Math.max(0.05, maxAbsValue * 1.2);
  if (padded <= 0.1) {
    return 0.1;
  }
  if (padded <= 0.5) {
    return Math.ceil(padded * 10) / 10;
  }
  return Math.ceil(padded * 2) / 2;
}

function createChartTickIndexes(rowCount) {
  if (rowCount <= 1) {
    return [0];
  }
  const indexes = [0, Math.floor((rowCount - 1) / 2), rowCount - 1];
  return Array.from(new Set(indexes));
}

function normalizeHistoryStats(apiStats, rows) {
  if (apiStats) {
    return {
      firstSeenAt: apiStats.first_seen_at ?? null,
      lastSeenAt: apiStats.last_seen_at ?? null,
      durationSeconds: getNumber(apiStats.duration_seconds),
      sampleCount: Number(apiStats.sample_count) || 0,
      latestSpread: toNullableNumber(apiStats.latest_spread_percent),
      minSpread: toNullableNumber(apiStats.min_spread_percent),
      maxSpread: toNullableNumber(apiStats.max_spread_percent),
      closedBefore: Boolean(apiStats.closed_before),
      closedCount: Number(apiStats.closed_count) || 0
    };
  }

  const spreads = rows
    .map((row) => toNullableNumber(row.selected_spread_percent))
    .filter((value) => value !== null);
  const latest = spreads.length ? spreads[spreads.length - 1] : null;
  return {
    firstSeenAt: rows[0]?.timestamp ?? null,
    lastSeenAt: rows[rows.length - 1]?.timestamp ?? null,
    durationSeconds: rows.length > 1
      ? Math.max(0, (new Date(rows[rows.length - 1].timestamp) - new Date(rows[0].timestamp)) / 1000)
      : 0,
    sampleCount: rows.length,
    latestSpread: latest,
    minSpread: spreads.length ? Math.min(...spreads) : null,
    maxSpread: spreads.length ? Math.max(...spreads) : null,
    closedBefore: false,
    closedCount: 0
  };
}

function createHistoryStatsItems(stats) {
  return [
    {
      label: "First seen",
      value: formatHistoryDate(stats.firstSeenAt)
    },
    {
      label: "Last seen",
      value: formatHistoryDate(stats.lastSeenAt)
    },
    {
      label: "Duration",
      value: formatHistoryDuration(stats.durationSeconds)
    },
    {
      label: "Latest spread",
      value: formatNullablePercent(stats.latestSpread)
    },
    {
      label: "Min spread",
      value: formatNullablePercent(stats.minSpread)
    },
    {
      label: "Max spread",
      value: formatNullablePercent(stats.maxSpread)
    },
    {
      label: "Closed before",
      value: stats.closedBefore ? "Yes" : "No",
      detail: `${formatNumber(stats.closedCount, 0)} close samples`
    },
    {
      label: "Samples",
      value: formatNumber(stats.sampleCount, 0)
    }
  ];
}

function formatHistoryDate(value) {
  return value ? formatDateTime(value) : "-";
}

function formatHistoryDuration(seconds) {
  const totalSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }

  return `${minutes}m`;
}

function formatNullablePercent(value) {
  return value === null ? "-" : formatPercent(value);
}

function formatChartTime(value) {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return "-";
  }

  return timestamp.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function getNumber(value) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : 0;
}

function toNullableNumber(value) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function DepthCheckCell({ depthCheck }) {
  return (
    <div className="depth-cell">
      <span className={`pill depth-${depthCheck.depth_status.toLowerCase()}`}>
        {depthCheck.depth_status}
      </span>
      <span>{formatUsd(depthCheck.target_notional_usd, 0)}</span>
      <span>Adj {formatOptionalPercent(depthCheck.depth_adjusted_raw_spread_percent)}</span>
      <span>
        Slip {formatOptionalPercent(depthCheck.long_slippage_percent)} / {formatOptionalPercent(depthCheck.short_slippage_percent)}
      </span>
    </div>
  );
}

function createEmptyFilters() {
  return {
    minRawSpread: "",
    minNetSpread: "",
    minVolume24hUsd: "",
    symbolQuery: "",
    sortBy: "net_spread",
    sortDir: "desc",
    limit: "100",
    exchanges: []
  };
}

function toUiFilters(apiFilters = {}) {
  return {
    minRawSpread: toNumericInputValue(apiFilters.min_raw_spread),
    minNetSpread: toNumericInputValue(apiFilters.min_net_spread),
    minVolume24hUsd: toNumericInputValue(apiFilters.min_volume_24h_usd),
    symbolQuery: "",
    sortBy: "net_spread",
    sortDir: "desc",
    limit: "100",
    exchanges: Array.isArray(apiFilters.exchanges) ? apiFilters.exchanges : []
  };
}

function normalizeFilters(filters) {
  return {
    minRawSpread: normalizeDecimalInput(filters.minRawSpread),
    minNetSpread: normalizeDecimalInput(filters.minNetSpread),
    minVolume24hUsd: normalizeDecimalInput(filters.minVolume24hUsd),
    symbolQuery: normalizeTextInput(filters.symbolQuery),
    sortBy: normalizeSortBy(filters.sortBy),
    sortDir: normalizeSortDir(filters.sortDir),
    limit: normalizeLimit(filters.limit),
    exchanges: Array.isArray(filters.exchanges) ? filters.exchanges : []
  };
}

function toNumericInputValue(value) {
  return value === null || value === undefined ? "" : String(value).replace(",", ".");
}

function normalizeDecimalInput(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value).trim().replace(",", ".");
}

function normalizeTextInput(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value).trim();
}

function normalizeSortBy(value) {
  return SORT_BY_OPTIONS.has(value) ? value : "net_spread";
}

function normalizeSortDir(value) {
  return value === "asc" ? "asc" : "desc";
}

function normalizeLimit(value) {
  const normalized = String(value ?? "100").trim();
  return LIMIT_OPTIONS.has(normalized) ? normalized : "100";
}

function getVisibleExchangeOptions(scannerStatus, settings, opportunities = []) {
  const statusEnabledExchanges = toStringArray(scannerStatus?.enabled_exchanges);
  const supportedExchanges = toStringArray(settings?.supported_exchanges);
  const opportunityExchanges = getOpportunityExchangeNames(opportunities);
  const statusAndDataExchanges = uniqueExchangeNames([
    ...statusEnabledExchanges,
    ...opportunityExchanges
  ]);

  if (scannerStatus?.mode !== "live") {
    return uniqueExchangeNames([
      ...statusAndDataExchanges,
      ...supportedExchanges
    ]);
  }

  const activeExchanges = getActiveExchangeOptions(
    scannerStatus,
    settings,
    opportunities
  );
  return activeExchanges.length
    ? activeExchanges
    : uniqueExchangeNames([
        ...statusAndDataExchanges,
        ...supportedExchanges
      ]);
}

function getActiveExchangeOptions(scannerStatus, settings, opportunities = []) {
  const statusEnabledExchanges = toStringArray(scannerStatus?.enabled_exchanges);
  const supportedExchanges = toStringArray(settings?.supported_exchanges);
  const opportunityExchanges = getOpportunityExchangeNames(opportunities);

  if (scannerStatus?.mode !== "live") {
    return uniqueExchangeNames([
      ...statusEnabledExchanges,
      ...opportunityExchanges,
      ...supportedExchanges
    ]);
  }

  const knownExchangeNames = uniqueExchangeNames([
    ...statusEnabledExchanges,
    ...supportedExchanges,
    ...opportunityExchanges
  ]);
  const connectorExchanges = toStringArray(scannerStatus?.active_connectors)
    .map((connector) => getExchangeNameForConnector(connector, knownExchangeNames))
    .filter(Boolean);

  return uniqueExchangeNames([
    ...statusEnabledExchanges,
    ...connectorExchanges,
    ...opportunityExchanges
  ]);
}

function getOpportunityExchangeNames(opportunities) {
  if (!Array.isArray(opportunities)) {
    return [];
  }

  return opportunities.flatMap((opportunity) => [
    opportunity.long_exchange,
    opportunity.short_exchange
  ]);
}

function getExchangeNameForConnector(connector, knownExchangeNames) {
  const connectorKey = normalizeExchangeKey(connector);
  if (!connectorKey) {
    return "";
  }

  const knownMatch = knownExchangeNames.find(
    (exchange) => normalizeExchangeKey(exchange) === connectorKey
  );
  if (knownMatch) {
    return knownMatch;
  }

  return EXCHANGE_LABEL_OVERRIDES[connectorKey] ?? toTitleCase(connectorKey);
}

function uniqueExchangeNames(exchanges) {
  const seen = new Set();
  const unique = [];

  for (const exchange of exchanges) {
    const label = normalizeTextInput(exchange);
    const key = normalizeExchangeKey(label);
    if (!label || !key || seen.has(key)) {
      continue;
    }

    seen.add(key);
    unique.push(label);
  }

  return unique;
}

function normalizeExchangeKey(exchange) {
  return normalizeTextInput(exchange).toLowerCase();
}

function toStringArray(value) {
  return Array.isArray(value) ? value : [];
}

function toTitleCase(value) {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function createEmptyOpportunityMessage(totalOpportunities, filteredOpportunities) {
  const foundCount = Number(totalOpportunities) || 0;
  const matchingCount = Number(filteredOpportunities) || 0;
  if (foundCount > 0 && matchingCount === 0) {
    return `Scanner found ${formatOpportunityCount(foundCount)}, but filters hide all results. Try lowering spread, volume, exchange, or symbol filters.`;
  }
  if (foundCount > 0) {
    return "No rows are displayed for the current limit or sorting state.";
  }

  return "Scanner has not stored any opportunities yet.";
}

function formatOpportunityCount(count) {
  return `${count} ${count === 1 ? "opportunity" : "opportunities"}`;
}

function formatConnectors(connectors) {
  if (!Array.isArray(connectors) || !connectors.length) {
    return "-";
  }

  return connectors.join(", ");
}

function formatModeLabel(mode) {
  if (mode === "live") {
    return "Live public data";
  }
  if (mode === "mock") {
    return "Mock data only";
  }

  return "-";
}

function formatMarketDataMode(mode) {
  if (mode === "websocket") {
    return "WebSocket";
  }
  if (mode === "rest") {
    return "REST";
  }

  return "-";
}

function formatWebSocketStatus(scannerStatus) {
  if (!scannerStatus?.websocket_enabled) {
    return "Off";
  }

  const connectionCounts = scannerStatus.websocket_connection_count ?? {};
  const chunkCounts = scannerStatus.websocket_chunk_count ?? {};
  const symbolCounts = scannerStatus.websocket_symbol_count ?? {};
  const lastErrors = scannerStatus.websocket_last_error ?? {};
  const activeExchanges = Array.isArray(scannerStatus.websocket_active_exchanges)
    ? scannerStatus.websocket_active_exchanges
    : [];
  if (!activeExchanges.length) {
    return "Starting";
  }

  const connectedConnectionCount = activeExchanges.reduce(
    (total, exchange) => total + (Number(connectionCounts[exchange]) || 0),
    0
  );
  const totalChunkCount = activeExchanges.reduce(
    (total, exchange) => total + (Number(chunkCounts[exchange]) || 0),
    0
  );
  const totalSymbolCount = activeExchanges.reduce(
    (total, exchange) => total + (Number(symbolCounts[exchange]) || 0),
    0
  );
  const staleCount = Number(scannerStatus.stale_snapshot_count) || 0;
  const hasError = activeExchanges.some((exchange) => Boolean(lastErrors[exchange]));
  const parts = [
    `${connectedConnectionCount}/${totalChunkCount || activeExchanges.length} conn`,
    `${totalSymbolCount} sym`
  ];
  if (staleCount > 0) {
    parts.push(`${staleCount} stale`);
  }
  if (hasError) {
    parts.push("error");
  }

  return parts.join(" - ");
}

function formatSymbolSelectionMode(mode) {
  if (mode === "auto") {
    return "Auto";
  }
  if (mode === "manual") {
    return "Manual";
  }

  return "-";
}

function formatSymbolsPreview(symbols) {
  if (!Array.isArray(symbols) || !symbols.length) {
    return "-";
  }

  return symbols.join(", ");
}

function formatDepthCheckNote(depthCheck) {
  if (!depthCheck) {
    return "";
  }

  if (!depthCheck.enabled) {
    return "Depth check disabled";
  }

  return `Depth checked top ${depthCheck.max_opportunities_to_check} opportunities for ${formatUsd(depthCheck.target_notional_usd, 0)} size`;
}

function formatAlertStatusLabel(alertStatus) {
  if (!alertStatus) {
    return "Loading";
  }

  return alertStatus.enabled ? "Enabled" : "Disabled";
}

function formatTelegramStatusLabel(telegramStatus) {
  if (!telegramStatus) {
    return "Loading";
  }
  if (!telegramStatus.enabled) {
    return "Disabled";
  }
  return telegramStatus.configured ? "Configured" : "Not configured";
}

function formatOptionalPercent(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "-";
  }

  return formatPercent(numericValue);
}

const EXCHANGE_LABEL_OVERRIDES = {
  okx: "OKX",
  kucoin: "KuCoin"
};

const HISTORY_INTERVALS = [
  { label: "Raw", value: "raw" },
  { label: "5m", value: "5m" },
  { label: "15m", value: "15m" },
  { label: "1h", value: "1h" }
];

const SORT_BY_OPTIONS = new Set([
  "raw_spread",
  "net_spread",
  "volume_24h",
  "symbol",
  "updated_at"
]);

const LIMIT_OPTIONS = new Set(["25", "50", "100", "250"]);

export default App;
