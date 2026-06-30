import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { api } from '@/api/client'
import type { JobResponse } from '@/types/api'

const ACTIVE_STATUSES = new Set(['pending', 'running'])
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobResponse[]>([])
  const currentScanJobId = ref<string | null>(null)
  const currentMultiAccountJobId = ref<string | null>(null)
  const error = ref<string | null>(null)
  let pollInterval: ReturnType<typeof setInterval> | null = null

  const activeJobs = computed(() =>
    jobs.value.filter((j) => ACTIVE_STATUSES.has(j.status)),
  )

  const hasActiveJobs = computed(() => activeJobs.value.length > 0)

  const currentScanJob = computed(() => {
    if (!currentScanJobId.value) return null
    return jobs.value.find((j) => j.id === currentScanJobId.value) || null
  })

  const currentMultiAccountJob = computed(() => {
    if (!currentMultiAccountJobId.value) return null
    return jobs.value.find((j) => j.id === currentMultiAccountJobId.value) || null
  })

  async function fetchJobs() {
    try {
      jobs.value = await api.listJobs()
      // Find any running scan job
      const runningScans = jobs.value.filter(
        (j) => j.job_type === 'scan' && ACTIVE_STATUSES.has(j.status),
      )
      if (runningScans.length > 0) {
        currentScanJobId.value = runningScans[0].id
        startPolling()
      }
      // Find any running multi-account job
      const runningMA = jobs.value.filter(
        (j) => j.job_type.startsWith('multi_account_') && ACTIVE_STATUSES.has(j.status),
      )
      if (runningMA.length > 0) {
        currentMultiAccountJobId.value = runningMA[0].id
        startPolling()
      }
    } catch (e) {
      console.error('Failed to fetch jobs:', e)
    }
  }

  async function pollJob(jobId: string): Promise<JobResponse | null> {
    try {
      const job = await api.getJob(jobId)
      // Update in local list
      const idx = jobs.value.findIndex((j) => j.id === jobId)
      if (idx >= 0) {
        jobs.value[idx] = job
      } else {
        jobs.value.unshift(job)
      }
      return job
    } catch {
      return null
    }
  }

  function startPolling() {
    if (pollInterval) return
    pollInterval = setInterval(async () => {
      if (!hasActiveJobs.value) {
        stopPolling()
        return
      }
      for (const job of activeJobs.value) {
        await pollJob(job.id)
      }
    }, 2000) // Poll every 2 seconds for faster updates
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  async function submitScan(services?: string[], regions?: string[]) {
    error.value = null
    try {
      const result = await api.submitScan({ services, regions })
      currentScanJobId.value = result.job_id
      await pollJob(result.job_id)
      startPolling()
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to submit scan'
      throw e
    }
  }

  async function submitDelete(services?: string[]) {
    error.value = null
    try {
      const result = await api.submitDelete({ services })
      await pollJob(result.job_id)
      startPolling()
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to submit delete'
      throw e
    }
  }

  async function cancelScan(jobId = currentScanJobId.value) {
    if (!jobId) return null
    error.value = null
    try {
      const job = await api.cancelJob(jobId)
      const idx = jobs.value.findIndex((j) => j.id === jobId)
      if (idx >= 0) {
        jobs.value[idx] = job
      } else {
        jobs.value.unshift(job)
      }
      return job
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to stop scan'
      throw e
    }
  }

  function clearCurrentScan() {
    currentScanJobId.value = null
  }

  async function submitMultiAccountJob(
    action: 'deploy' | 'update' | 'remove' | 'clean',
    body?: Record<string, unknown>,
  ) {
    error.value = null
    try {
      let result: { job_id: string; job_type: string; status: string; message: string }
      switch (action) {
        case 'deploy':
          result = await api.deployMultiAccount(body as any)
          break
        case 'update':
          result = await api.updateMultiAccount()
          break
        case 'remove':
          result = await api.removeMultiAccount()
          break
        case 'clean':
          result = await api.deployMultiAccount({ force_recreate: true })
          break
      }
      currentMultiAccountJobId.value = result.job_id
      await pollJob(result.job_id)
      startPolling()
      return result
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to submit multi-account job'
      throw e
    }
  }

  function clearCurrentMultiAccount() {
    currentMultiAccountJobId.value = null
  }

  // Auto-cleanup: clear currentScanJobId 60s after terminal state
  let cleanupTimer: ReturnType<typeof setTimeout> | null = null

  watch(currentScanJob, (job) => {
    if (cleanupTimer) {
      clearTimeout(cleanupTimer)
      cleanupTimer = null
    }
    if (job && TERMINAL_STATUSES.has(job.status)) {
      cleanupTimer = setTimeout(() => {
        currentScanJobId.value = null
        cleanupTimer = null
      }, 60000)
    }
  })

  // Auto-cleanup for multi-account jobs
  let maCleanupTimer: ReturnType<typeof setTimeout> | null = null

  watch(currentMultiAccountJob, (job) => {
    if (maCleanupTimer) {
      clearTimeout(maCleanupTimer)
      maCleanupTimer = null
    }
    if (job && TERMINAL_STATUSES.has(job.status)) {
      maCleanupTimer = setTimeout(() => {
        currentMultiAccountJobId.value = null
        maCleanupTimer = null
      }, 60000)
    }
  })

  // Auto-fetch jobs on store init to recover state
  fetchJobs()

  return {
    jobs,
    activeJobs,
    hasActiveJobs,
    currentScanJob,
    currentScanJobId,
    currentMultiAccountJob,
    currentMultiAccountJobId,
    error,
    fetchJobs,
    pollJob,
    startPolling,
    stopPolling,
    submitScan,
    cancelScan,
    submitDelete,
    clearCurrentScan,
    submitMultiAccountJob,
    clearCurrentMultiAccount,
  }
})
