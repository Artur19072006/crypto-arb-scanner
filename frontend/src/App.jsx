import { useEffect, useMemo, useState } from "react";

import { fetchOpportunities, fetchSettings, fetchStatus } from "./api.js";
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatUsd
} from "./formatters.js";

function App() {
  const [opportunities, setOpportunities] = useState([]);
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
        const [data, loadedScannerStatus] = await Promise.all([
          fetchOpportunities(appliedFilters),
          fetchStatus()
        ]);
        if (isMounted) {
          setOpportunities(data);
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
          <strong>{totalOpportunities}</strong>
        </div>
        <div>
          <span className="metric-label">Matching filters</span>
          <strong>{opportunities.length}</strong>
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
          totalOpportunities={totalOpportunities}
        />
      )}
    </main>
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

function OpportunitiesTable({ opportunities, status, totalOpportunities }) {
  const emptyMessage =
    status === "loading"
      ? "Loading opportunities..."
      : createEmptyOpportunityMessage(totalOpportunities);

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
              <th>24h volume</th>
              <th>Size</th>
              <th>Funding</th>
              <th>Liquidity</th>
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
              </tr>
            ))}
            {!opportunities.length && (
              <tr>
                <td colSpan="11" className="empty-state">
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

function createEmptyFilters() {
  return {
    minRawSpread: "",
    minNetSpread: "",
    minVolume24hUsd: "",
    exchanges: []
  };
}

function toUiFilters(apiFilters = {}) {
  return {
    minRawSpread: toNumericInputValue(apiFilters.min_raw_spread),
    minNetSpread: toNumericInputValue(apiFilters.min_net_spread),
    minVolume24hUsd: toNumericInputValue(apiFilters.min_volume_24h_usd),
    exchanges: Array.isArray(apiFilters.exchanges) ? apiFilters.exchanges : []
  };
}

function normalizeFilters(filters) {
  return {
    minRawSpread: normalizeDecimalInput(filters.minRawSpread),
    minNetSpread: normalizeDecimalInput(filters.minNetSpread),
    minVolume24hUsd: normalizeDecimalInput(filters.minVolume24hUsd),
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

function createEmptyOpportunityMessage(totalOpportunities) {
  const foundCount = Number(totalOpportunities) || 0;
  if (foundCount > 0) {
    return `Scanner found ${formatOpportunityCount(foundCount)}, but 0 match the applied filters. Try lowering min spread, net spread, or volume.`;
  }

  return "Scanner has not found any opportunities yet.";
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

const CONNECTOR_EXCHANGE_NAMES = {
  binance: "Binance",
  bybit: "Bybit"
};

export default App;
