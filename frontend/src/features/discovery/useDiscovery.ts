import { useEffect, useRef, useState } from 'react'
import type { Place, PlaceQuery } from '../../types/place'
import type { PlaceService } from '../../services/PlaceService'

const initialQuery: PlaceQuery = { q: '', area: '', category: '', facilities: [] }

export function useDiscovery(service: PlaceService) {
  const [query, setQuery] = useState<PlaceQuery>(initialQuery)
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [resultsRevision, setResultsRevision] = useState(0)
  const latestRequest = useRef(0)
  const activeController = useRef<AbortController | null>(null)

  const search = async (nextQuery = query) => {
    const requestId = ++latestRequest.current
    activeController.current?.abort()
    const controller = new AbortController()
    activeController.current = controller
    setLoading(true)
    try {
      const results = await service.listPlaces(nextQuery, controller.signal)
      if (requestId === latestRequest.current) {
        setPlaces(results)
        setResultsRevision((revision) => revision + 1)
        setError(false)
      }
    } catch {
      if (requestId === latestRequest.current) setError(true)
    } finally {
      if (requestId === latestRequest.current) {
        setLoading(false)
        setHasLoaded(true)
      }
    }
  }

  const updateQuery = (nextQuery: PlaceQuery) => {
    setQuery(nextQuery)
    void search(nextQuery)
  }

  useEffect(() => {
    const requestId = ++latestRequest.current
    const controller = new AbortController()
    activeController.current = controller
    void service
      .listPlaces(initialQuery, controller.signal)
      .then((results) => {
        if (requestId === latestRequest.current) {
          setPlaces(results)
          setResultsRevision((revision) => revision + 1)
          setError(false)
        }
      })
      .catch(() => {
        if (requestId === latestRequest.current) setError(true)
      })
      .finally(() => {
        if (requestId === latestRequest.current) {
          setLoading(false)
          setHasLoaded(true)
        }
      })
    return () => {
      latestRequest.current += 1
      activeController.current?.abort()
    }
  }, [service])
  return {
    query,
    places,
    loading,
    error,
    hasLoaded,
    resultsRevision,
    updateQuery,
    refresh: () => search(),
  }
}
