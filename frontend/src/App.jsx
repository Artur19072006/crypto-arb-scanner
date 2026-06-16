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
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadOpportunities() {
      try {
        const data = await fetchOpportunities();
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
  }, []);

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
          <span>{status === "ready" ? "Mock data online" : status}</span>
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
          <strong>Mock bid/ask</strong>
        </div>
      </section>

      {status === "error" ? (
        <p className="error-message">{error}</p>
      ) : (
        <OpportunitiesTable opportunities={opportunities} />
      )}
    </main>
  );
}

function OpportunitiesTable({ opportunities }) {
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
                  Loading opportunities...
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
