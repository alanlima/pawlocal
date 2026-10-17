import { useEffect, useRef, useState } from 'react'
import type { Place, PlaceQuery } from '../../types/place'
import type { PlaceService } from '../../services/PlaceService'

export function useDiscovery(service: PlaceService) {
  const [query, setQuery] = useState<PlaceQuery>({ q: '', area: '', category: '', facilities: [] })
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const latestRequest = useRef(0)

  const search = async (nextQuery = query) => {
    const requestId = ++latestRequest.current
    setLoading(true)
    setError(false)
    try {
      const results = await service.listPlaces(nextQuery)
      if (requestId === latestRequest.current) setPlaces(results)
    } catch {
      if (requestId === latestRequest.current) setError(true)
    } finally {
      if (requestId === latestRequest.current) setLoading(false)
    }
  }

  const updateQuery = (nextQuery: PlaceQuery) => {
    setQuery(nextQuery)
    void search(nextQuery)
  }

  useEffect(() => { void search() }, [])
  return { query, places, loading, error, updateQuery, refresh: () => search() }
}
