import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type {
  CostSummaryResponse,
  CostByServiceResponse,
  CostByAccountResponse,
  CostForecastResponse,
  CostGenericResponse,
  CostCommitmentsResponse,
  CostServiceDeepDiveResponse,
  CostTrendsRequest,
  CostTrendsResponse,
  CostAnomaliesRequest,
  CostAnomaliesResponse,
  CostChargebackRequest,
  CostChargebackResponse,
  CostGapsRequest,
  CostGapsResponse,
} from '@/types/api'

export const useCostStore = defineStore('cost', () => {
  const summary = ref<CostSummaryResponse | null>(null)
  const byService = ref<CostByServiceResponse | null>(null)
  const byAccount = ref<CostByAccountResponse | null>(null)
  const forecast = ref<CostForecastResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const days = ref(30)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const [s, svc, acc] = await Promise.all([
        api.costSummary({ days: days.value }),
        api.costByService({ days: days.value }),
        api.costByAccount({ days: days.value }),
      ])
      summary.value = s
      byService.value = svc
      byAccount.value = acc
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch cost data'
    } finally {
      loading.value = false
    }
  }

  async function fetchForecast(forecastDays = 30) {
    try {
      forecast.value = await api.costForecast({ days: forecastDays, method: 'average' })
    } catch (e) {
      console.error('Forecast failed:', e)
    }
  }

  function setDays(d: number) {
    days.value = d
    fetchAll()
  }

  // --- New: on-demand data sections ---
  const regions = ref<CostGenericResponse | null>(null)
  const daily = ref<CostGenericResponse | null>(null)
  const topResources = ref<CostGenericResponse | null>(null)
  const dataTransfer = ref<CostGenericResponse | null>(null)
  const savingsPlans = ref<CostCommitmentsResponse | null>(null)
  const reservations = ref<CostCommitmentsResponse | null>(null)
  const serviceDeepDive = ref<CostServiceDeepDiveResponse | null>(null)
  const trends = ref<CostTrendsResponse | null>(null)
  const anomalies = ref<CostAnomaliesResponse | null>(null)
  const chargebackReport = ref<CostChargebackResponse | null>(null)
  const gaps = ref<CostGapsResponse | null>(null)
  const sectionLoading = ref(false)
  const sectionError = ref<string | null>(null)

  async function fetchRegions() {
    sectionLoading.value = true
    sectionError.value = null
    try {
      regions.value = await api.costRegions({ days: days.value })
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch region data'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchDaily() {
    sectionLoading.value = true
    sectionError.value = null
    try {
      daily.value = await api.costDaily({ days: days.value })
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch daily data'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchTopResources(limit = 50) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      topResources.value = await api.costTopResources({ days: days.value, limit })
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch top resources'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchDataTransfer() {
    sectionLoading.value = true
    sectionError.value = null
    try {
      dataTransfer.value = await api.costDataTransfer({ days: days.value })
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch data transfer costs'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchCommitments() {
    sectionLoading.value = true
    sectionError.value = null
    try {
      const [sp, ri] = await Promise.all([
        api.costSavingsPlans({ days: days.value }),
        api.costReservations({ days: days.value }),
      ])
      savingsPlans.value = sp
      reservations.value = ri
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch commitments data'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchServiceDeepDive(service: string, view: string) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      const methods: Record<string, (p: { days?: number; view?: string }) => Promise<CostServiceDeepDiveResponse>> = {
        ec2: api.costEC2,
        s3: api.costS3,
        rds: api.costRDS,
        lambda: api.costLambda,
      }
      const fn = methods[service.toLowerCase()]
      if (fn) {
        serviceDeepDive.value = await fn({ days: days.value, view })
      }
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Failed to fetch service data'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchTrends(params: CostTrendsRequest) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      trends.value = await api.costTrends(params)
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Trend analysis failed'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchAnomalies(params: CostAnomaliesRequest) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      anomalies.value = await api.costAnomalies(params)
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Anomaly detection failed'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchChargeback(params: CostChargebackRequest) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      chargebackReport.value = await api.costChargeback(params)
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Chargeback report failed'
    } finally {
      sectionLoading.value = false
    }
  }

  async function fetchGaps(params: CostGapsRequest) {
    sectionLoading.value = true
    sectionError.value = null
    try {
      gaps.value = await api.costGaps(params)
    } catch (e) {
      sectionError.value = e instanceof Error ? e.message : 'Gap analysis failed'
    } finally {
      sectionLoading.value = false
    }
  }

  return {
    summary,
    byService,
    byAccount,
    forecast,
    loading,
    error,
    days,
    fetchAll,
    fetchForecast,
    setDays,
    // New
    regions,
    daily,
    topResources,
    dataTransfer,
    savingsPlans,
    reservations,
    serviceDeepDive,
    trends,
    anomalies,
    chargebackReport,
    gaps,
    sectionLoading,
    sectionError,
    fetchRegions,
    fetchDaily,
    fetchTopResources,
    fetchDataTransfer,
    fetchCommitments,
    fetchServiceDeepDive,
    fetchTrends,
    fetchAnomalies,
    fetchChargeback,
    fetchGaps,
  }
})
