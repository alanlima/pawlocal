import type { Attributes } from '@opentelemetry/api'
import type { PlaceService } from './PlaceService'
import { recordDemoAction, recordOperation } from '../observability/telemetry'

const allowedCategories = new Set(['dog_park', 'beach', 'walk', 'hiking_area', 'cafe'])

export function observePlaceService(service: PlaceService): PlaceService {
  return {
    listPlaces: (query, signal) =>
      recordOperation(
        'search',
        () => service.listPlaces(query, signal),
        (places) => (places.length ? 'success' : 'empty'),
        {
          ...(allowedCategories.has(query.category ?? '') ? { category: query.category } : {}),
        } as Attributes,
      ),
    getPlace: (id) =>
      recordOperation(
        'detail',
        () => service.getPlace(id),
        (place) => (place ? 'success' : 'not_found'),
      ),
    listFavourites: () => service.listFavourites(),
    toggleFavourite: (id) => recordOperation('favourite', () => service.toggleFavourite(id)),
    submitContribution: async (input) => {
      try {
        const result = await recordOperation(
          'contribution',
          () => service.submitContribution(input),
          undefined,
          { kind: input.kind },
        )
        recordDemoAction('contribution', 'success', input.kind)
        return result
      } catch (error) {
        recordDemoAction('contribution', 'error', input.kind)
        throw error
      }
    },
    listReportableContributions: () => service.listReportableContributions(),
    submitReport: async (input) => {
      try {
        await recordOperation('report', () => service.submitReport(input), undefined, {
          target_type: input.targetType,
        })
        recordDemoAction('report', 'success', input.targetType)
      } catch (error) {
        recordDemoAction('report', 'error', input.targetType)
        throw error
      }
    },
  }
}
