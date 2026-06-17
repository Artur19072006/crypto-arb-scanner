import { useEffect, useMemo, useState } from "react";

import {
  fetchAlerts,
  fetchAlertStatus,
  fetchOpportunities,
  fetchSettings,
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
    () => getVisibleExchangeOptions(scannerStatus, settings),
    [scannerStatus, settings]
  );
  const activeExchangeOptions = useMemo(
    () => getActiveExchangeOptions(scannerStatus, settings),
    [scannerStatus, settings]
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
  const depthCheckNote = formatDepthCheckNote(settings?.depth_check);

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

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Local scanner</p>
          <h1>Perpetual Futures Arbitrage</h1>
        </div>
        <div className="status-panel">
          <span className={`status-dot status-${requestStatus}`} aria-hidden="true" />
          <span>{requestStatus === "ready" ? formatModeLabel(scannerStatus?.mode) : requestStatus}</span>
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

      {Array.isArray(scannerStatus?.selected_symbols) && scannerStatus.selected_symbols.length > 0 && (
        <section className="symbol-preview" aria-label="Selected symbols preview">
          <span className="metric-label">Preview</span>
          <strong>{formatSymbolsPreview(scannerStatus.selected_symbols)}</strong>
        </section>
      )}

      {depthCheckNote && (
        <section className="depth-note" aria-label="Depth check status">
          <span className="metric-label">Depth</span>
          <strong>{depthCheckNote}</strong>
        </section>
      )}

      <AlertsPanel
        alertStatus={alertStatus}
        telegramStatus={telegramStatus}
        alerts={alerts}
      />

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
  filteredOpportunities
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
              <th>Long</th>
              <th>Short</th>
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
                <td colSpan={hasDepthData ? 13 : 12} className="empty-state">
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

function getVisibleExchangeOptions(scannerStatus, settings) {
  const supportedExchanges = Array.isArray(settings?.supported_exchanges)
    ? settings.supported_exchanges
    : [];

  if (scannerStatus?.mode !== "live") {
    return supportedExchanges;
  }

  const activeExchanges = getActiveExchangeOptions(scannerStatus, settings);
  return activeExchanges.length ? activeExchanges : supportedExchanges;
}

function getActiveExchangeOptions(scannerStatus, settings) {
  if (scannerStatus?.mode !== "live") {
    return Array.isArray(settings?.supported_exchanges) ? settings.supported_exchanges : [];
  }

  const supportedExchanges = new Set(settings?.supported_exchanges ?? []);
  const mappedExchanges = (scannerStatus?.active_connectors ?? [])
    .map((connector) => CONNECTOR_EXCHANGE_NAMES[connector])
    .filter(Boolean);

  return mappedExchanges.filter((exchange) => (
    !supportedExchanges.size || supportedExchanges.has(exchange)
  ));
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

const CONNECTOR_EXCHANGE_NAMES = {
  binance: "Binance",
  bybit: "Bybit",
  okx: "OKX"
};

const SORT_BY_OPTIONS = new Set([
  "raw_spread",
  "net_spread",
  "volume_24h",
  "symbol",
  "updated_at"
]);

const LIMIT_OPTIONS = new Set(["25", "50", "100", "250"]);

export default App;
