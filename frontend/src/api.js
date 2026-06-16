export async function fetchOpportunities() {
  const response = await fetch("/api/opportunities");

  if (!response.ok) {
    throw new Error(`Failed to load opportunities: ${response.status}`);
  }

  return response.json();
}
