import http from './http'

export const getAdminUsageOverview = async (days = 30) => (await http.get('/admin/usage/overview', { params: { days } })).data
export const getAdminUsageTrend = async (days = 30) => (await http.get('/admin/usage/trend', { params: { days } })).data
export const getAdminUsageUsers = async (offset = 0, limit = 20) => (await http.get('/admin/usage/users', { params: { offset, limit } })).data
export const getAdminUsageRecords = async (params = {}) => {
  const normalized = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== '' && value != null),
  )
  return (await http.get('/admin/usage/records/filter', { params: normalized })).data
}
export const adjustUserQuota = async (userId, payload) => (await http.put(`/admin/users/${userId}/quota`, payload)).data
