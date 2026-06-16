export async function fetchOpportunities(filters = {}) {
  const params = new URLSearchParams();

  addNumericParam(params, "min_raw_spread", filters.minRawSpread);
  addNumericParam(params, "min_net_spread", filters.minNetSpread);
  addNumericParam(params, "min_volume_24h_usd", filters.minVolume24hUsd);
  addExchangeParams(params, filters.exchanges);

  const query = params.toString();
  const response = await fetch(`/api/opportunities${query ? `?${query}` : ""}`);

  if (!response.ok) {
    throw new Error(`Failed to load opportunities: ${response.status}`);
  }

  return response.json();
}

export async function fetchSettings() {
  const response = await fetch("/api/settings");

  if (!response.ok) {
    throw new Error(`Failed to load settings: ${response.status}`);
  }

  return response.json();
}

export async function fetchStatus() {
  const response = await fetch("/api/status");

  if (!response.ok) {
    throw new Error(`Failed to load scanner status: ${response.status}`);
  }

  return response.json();
}

function addNumericParam(params, key, value) {
  if (value === undefined || value === null || value === "") {
    return;
  }

  const normalized = String(value).trim().replace(",", ".");
  if (!normalized) {
    return;
  }

  params.set(key, normalized);
}

function addExchangeParams(params, exchanges) {
  if (!Array.isArray(exchanges)) {
    return;
  }

  if (!exchanges.length) {
    params.set("exchanges", "");
    return;
  }

  for (const exchange of exchanges) {
    params.append("exchanges", exchange);
  }
}
