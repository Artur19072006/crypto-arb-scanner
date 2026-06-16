import { useEffect, useMemo, useState } from "react";

import { fetchOpportunities } from "./api.js";
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatUsd
} from "./formatters.js";

function App() {
  const [opportunities, setOpportunities] = useState([]);
  const [filters, setFilters] = useState({
    minRawSpread: "",
    minNetSpread: "",
    minVolume24hUsd: ""
  });
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadOpportunities() {
      setStatus("loading");
      setError("");

      try {
        const data = await fetchOpportunities(filters);
        if (isMounted) {
          setOpportunities(data);
          setStatus("ready");
        }
      } catch (loadError) {
        if (isMounted) {
          setError(loadError.message);
          setStatus("error");
        }
      }
    }

    loadOpportunities();

    return () => {
      isMounted = false;
    };
  }, [filters]);

  const lastUpdated = useMemo(() => {
    if (!opportunities.length) {
      return "-";
    }

    return formatDateTime(opportunities[0].timestamp);
  }, [opportunities]);

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Local scanner</p>
          <h1>Perpetual Futures Arbitrage</h1>
        </div>
        <div className="status-panel">
          <span className={`status-dot status-${status}`} aria-hidden="true" />
          <span>{status === "ready" ? "Mock data only" : status}</span>
        </div>
      </header>

      <section className="metrics-band" aria-label="Scanner summary">
        <div>
          <span className="metric-label">Opportunities</span>
          <strong>{opportunities.length}</strong>
        </div>
        <div>
          <span className="metric-label">Last update</span>
          <strong>{lastUpdated}</strong>
        </div>
        <div>
          <span className="metric-label">Data source</span>
          <strong>Mock snapshots</strong>
        </div>
      </section>

      <FilterControls filters={filters} onChange={setFilters} />

      {status === "error" ? (
        <p className="error-message">{error}</p>
      ) : (
        <OpportunitiesTable opportunities={opportunities} status={status} />
      )}
    </main>
  );
}

function FilterControls({ filters, onChange }) {
  function updateFilter(key, value) {
    onChange((currentFilters) => ({
      ...currentFilters,
      [key]: value
    }));
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
        />
      </label>
    </section>
  );
}

function OpportunitiesTable({ opportunities, status }) {
  const emptyMessage =
    status === "loading"
      ? "Loading opportunities..."
      : "No opportunities match the current filters.";

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

export default App;
