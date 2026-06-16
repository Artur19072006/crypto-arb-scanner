export async function fetchOpportunities(filters = {}) {
  const params = new URLSearchParams();

  addNumericParam(params, "min_raw_spread", filters.minRawSpread);
  addNumericParam(params, "min_net_spread", filters.minNetSpread);
  addNumericParam(params, "min_volume_24h_usd", filters.minVolume24hUsd);
  addTextParam(params, "symbol_query", filters.symbolQuery);
  addTextParam(params, "sort_by", filters.sortBy);
  addTextParam(params, "sort_dir", filters.sortDir);
  addNumericParam(params, "limit", filters.limit);
  addExchangeParams(params, filters.exchanges);

  const query = params.toString();
  const response = await fetch(`/api/opportunities${query ? `?${query}` : ""}`);

  if (!response.ok) {
    throw new Error(`Failed to load opportunities: ${response.status}`);
  }

  const payload = await response.json();
  if (Array.isArray(payload)) {
    return {
      opportunities: payload,
      total_stored_opportunity_count: payload.length,
      filtered_opportunity_count: payload.length,
      returned_count: payload.length,
      sort_by: filters.sortBy ?? "net_spread",
      sort_dir: filters.sortDir ?? "desc",
      limit: Number(filters.limit) || 100
    };
  }

  return payload;
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

function addTextParam(params, key, value) {
  if (value === undefined || value === null || value === "") {
    return;
  }

  const normalized = String(value).trim();
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
