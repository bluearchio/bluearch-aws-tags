import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export const useLicenseStore = defineStore('license', () => {
  const loading = ref(false)
  const data = ref({
    tier: 'enterprise' as const,
    customer: 'local',
    features: {} as Record<string, boolean>,
  })

  const tier = computed(() => data.value.tier)
  const isFree = computed(() => false)
  const isPro = computed(() => true)
  const isEnterprise = computed(() => true)
  const customer = computed(() => data.value.customer)

  function isFeatureAllowed(_feature: string): boolean {
    return true
  }

  async function load() {
    return undefined
  }

  return {
    data,
    loading,
    tier,
    isFree,
    isPro,
    isEnterprise,
    customer,
    isFeatureAllowed,
    load,
  }
})
