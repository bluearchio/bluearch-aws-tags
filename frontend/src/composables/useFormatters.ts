/**
 * Shared formatting utilities for dates, currency, and lifecycle states.
 */
export function useFormatters() {
  function formatDate(dateStr?: string | null): string {
    if (!dateStr) return 'N/A'
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    } catch {
      return dateStr
    }
  }

  function formatDateTime(dateStr?: string | null): string {
    if (!dateStr) return 'N/A'
    try {
      return new Date(dateStr).toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return dateStr
    }
  }

  function formatCurrency(amount: number, currency = 'USD'): string {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount)
  }

  function stateClass(state?: string): string {
    switch (state) {
      case 'active':
        return 'state-active'
      case 'warned':
        return 'state-warned'
      case 'marked_for_deletion':
      case 'deleted':
        return 'state-danger'
      default:
        return ''
    }
  }

  function daysClass(days?: number | null): string {
    if (days === undefined || days === null) return ''
    if (days <= 3) return 'days-critical'
    if (days <= 7) return 'days-warning'
    return 'days-ok'
  }

  function truncateArn(arn: string, maxLen = 60): string {
    if (arn.length <= maxLen) return arn
    return arn.slice(0, maxLen - 3) + '...'
  }

  return {
    formatDate,
    formatDateTime,
    formatCurrency,
    stateClass,
    daysClass,
    truncateArn,
  }
}
