import http from './http.js'

export async function getTelemetryStats() {
  const response = await http.get('/admin/telemetry/stats')
  return response.data
}
