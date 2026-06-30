import { ref } from 'vue'
import type { SSEEvent } from '@/types/api'

/**
 * Composable for consuming SSE (Server-Sent Events) async generators.
 */
export function useSSE() {
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  async function consumeStream(
    generator: AsyncGenerator<SSEEvent>,
    onText: (text: string) => void,
    onDone?: (data: Record<string, unknown>) => void,
    onError?: (err: string) => void,
  ) {
    isStreaming.value = true
    error.value = null

    try {
      for await (const event of generator) {
        if (event.type === 'text' && typeof event.content === 'string') {
          onText(event.content)
        } else if (event.type === 'done') {
          onDone?.(event.content as Record<string, unknown>)
        } else if (event.type === 'error') {
          const errMsg = typeof event.content === 'string' ? event.content : 'Stream error'
          error.value = errMsg
          onError?.(errMsg)
        }
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : 'Stream failed'
      error.value = errMsg
      onError?.(errMsg)
    } finally {
      isStreaming.value = false
    }
  }

  return { isStreaming, error, consumeStream }
}
