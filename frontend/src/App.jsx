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

  function applyFilters() {
    setAppliedFilters(normalizeFilters(draftFilters));
  }

  function resetFilters() {
    const restoredFilters = normalizeFilters(defaultFilters);
    setDraftFilters(restoredFilters);
    setAppliedFilters(restoredFilters);
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
          <span className="metric-label">Last update</span>
          <strong>{lastUpdated}</strong>
        </div>
        <div>
          <span className="metric-label">Data source</span>
          <strong>{scannerStatus?.data_source ?? "Mock snapshots"}</strong>
        </div>
        <div>
          <span className="metric-label">Opportunities</span>
          <strong>{scannerStatus?.opportunity_count ?? opportunities.length}</strong>
        </div>
        <div>
          <span className="metric-label">Connectors</span>
          <strong>{formatConnectors(scannerStatus?.active_connectors)}</strong>
        </div>
      </section>

      <FilterControls
        filters={draftFilters}
        supportedExchanges={settings?.supported_exchanges ?? []}
        onChange={setDraftFilters}
        onApply={applyFilters}
        onReset={resetFilters}
        disabled={!settings}
      />

      {requestStatus === "error" ? (
        <p className="error-message">{error}</p>
      ) : (
        <OpportunitiesTable opportunities={opportunities} status={requestStatus} />
      )}
    </main>
  );
}

function FilterControls({
  filters,
  supportedExchanges,
  onChange,
  onApply,
  onReset,
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
          type="number"
          min="0"
          step="0.01"
          value={filters.minRawSpread}
          onChange={(event) => updateFilter("minRawSpread", event.target.value)}
          placeholder="0.10"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Min net spread</span>
        <input
          type="number"
          step="0.01"
          value={filters.minNetSpread}
          onChange={(event) => updateFilter("minNetSpread", event.target.value)}
          placeholder="0.00"
          disabled={disabled}
        />
      </label>
      <label>
        <span>Min 24h volume</span>
        <input
          type="number"
          min="0"
          step="10000"
          value={filters.minVolume24hUsd}
          onChange={(event) => updateFilter("minVolume24hUsd", event.target.value)}
          placeholder="400000"
          disabled={disabled}
        />
      </label>
      <fieldset className="exchange-filter">
        <legend>Exchanges</legend>
        <div className="exchange-options">
          {supportedExchanges.map((exchange) => (
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
        </div>
      </fieldset>
      <div className="filter-actions">
        <button type="button" onClick={onApply} disabled={disabled}>
          Apply filters
        </button>
        <button type="button" className="secondary-button" onClick={onReset} disabled={disabled}>
          Reset filters
        </button>
      </div>
    </section>
  );
}

function OpportunitiesTable({ opportunities, status }) {
  const emptyMessage =
    status === "loading"
      ? "Loading opportunities..."
      : "No opportunities match the applied filters.";

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
    minRawSpread: toInputValue(apiFilters.min_raw_spread),
    minNetSpread: toInputValue(apiFilters.min_net_spread),
    minVolume24hUsd: toInputValue(apiFilters.min_volume_24h_usd),
    exchanges: Array.isArray(apiFilters.exchanges) ? apiFilters.exchanges : []
  };
}

function normalizeFilters(filters) {
  return {
    minRawSpread: filters.minRawSpread,
    minNetSpread: filters.minNetSpread,
    minVolume24hUsd: filters.minVolume24hUsd,
    exchanges: Array.isArray(filters.exchanges) ? filters.exchanges : []
  };
}

function toInputValue(value) {
  return value === null || value === undefined ? "" : String(value);
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

export default App;
