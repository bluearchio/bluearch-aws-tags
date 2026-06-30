import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { AccountContextResponse } from '@/types/api'

export const useContextStore = defineStore('context', () => {
    const current = ref<AccountContextResponse | null>(null)
    const all = ref<AccountContextResponse[]>([])
    const loading = ref(false)

    const currentLabel = computed(() => {
        if (!current.value) return 'No Account'
        const alias = current.value.account_alias
        const id = current.value.account_id
        return alias ? `${alias} (${id})` : id
    })

    async function loadCurrent() {
        try {
            current.value = await api.currentContext()
        } catch {
            current.value = null
        }
    }

    async function loadAll() {
        loading.value = true
        try {
            const data = await api.allContexts()
            all.value = data.contexts
        } catch {
            // handled by API client
        } finally {
            loading.value = false
        }
    }

    async function switchTo(accountId: string) {
        loading.value = true
        try {
            current.value = await api.switchContext({ account_id: accountId })
            await loadAll()
            // Reload page to refresh all data for new context
            window.location.reload()
        } catch {
            // handled by API client
        } finally {
            loading.value = false
        }
    }

    return { current, all, loading, currentLabel, loadCurrent, loadAll, switchTo }
})
