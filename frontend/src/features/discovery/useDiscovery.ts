import { useEffect, useState } from 'react'
import type { Place, PlaceQuery } from '../../types/place'
import type { PlaceService } from '../../services/PlaceService'

export function useDiscovery(service: PlaceService) {
  const [query, setQuery] = useState<PlaceQuery>({ q: '', area: '', category: '', facilities: [] })
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const search = async (nextQuery = query) => {
    setLoading(true)
    setError(false)
    try { setPlaces(await service.listPlaces(nextQuery)) }
    catch { setError(true) }
    finally { setLoading(false) }
  }

  const updateQuery = (nextQuery: PlaceQuery) => {
    setQuery(nextQuery)
    void search(nextQuery)
  }

  useEffect(() => { void search() }, [])
  return { query, places, loading, error, updateQuery, refresh: () => search() }
}
