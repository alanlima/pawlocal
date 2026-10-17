import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { demoPlaces } from '../../data/demo-places'
import type { PlaceService } from '../../services/PlaceService'
import { useDiscovery } from './useDiscovery'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('useDiscovery', () => {
  it('ignores stale success and failure responses when a newer query is active', async () => {
    const oldRequest = deferred<typeof demoPlaces>()
    const newRequest = deferred<typeof demoPlaces>()
    const service = { listPlaces: vi.fn().mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise) } as unknown as PlaceService
    const { result } = renderHook(() => useDiscovery(service))

    act(() => result.current.updateQuery({ q: 'current query' }))
    await act(async () => { newRequest.resolve([demoPlaces[1]]); await newRequest.promise })
    await waitFor(() => expect(result.current.places).toEqual([demoPlaces[1]]))
    await act(async () => { oldRequest.reject(new Error('late stale failure')); await oldRequest.promise.catch(() => undefined) })

    expect(result.current.places).toEqual([demoPlaces[1]])
    expect(result.current.error).toBe(false)
    expect(result.current.loading).toBe(false)
  })

  it('aborts the previous service request when a new search supersedes it', () => {
    const signals: AbortSignal[] = []
    const service = { listPlaces: vi.fn((_query: unknown, signal?: AbortSignal) => {
      if (signal) signals.push(signal)
      return new Promise<typeof demoPlaces>(() => undefined)
    }) } as unknown as PlaceService
    const { result, unmount } = renderHook(() => useDiscovery(service))
    act(() => result.current.updateQuery({ q: 'new search' }))
    expect(signals[0].aborted).toBe(true)
    expect(signals[1].aborted).toBe(false)
    unmount()
    expect(signals[1].aborted).toBe(true)
  })
})
