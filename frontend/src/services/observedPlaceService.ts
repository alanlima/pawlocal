import type { Attributes } from '@opentelemetry/api'
import type { PlaceService } from './PlaceService'
import { recordDemoAction, recordOperation, traceContextForSpan } from '../observability/telemetry'

const allowedCategories = new Set(['dog_park', 'beach', 'walk', 'hiking_area', 'cafe'])

export function observePlaceService(service: PlaceService): PlaceService {
  return {
    listPlaces: (query, signal) =>
      recordOperation(
        'search',
        (span) => service.listPlaces(query, signal, traceContextForSpan(span)),
        (places) => (places.length ? 'success' : 'empty'),
        {
          ...(allowedCategories.has(query.category ?? '') ? { category: query.category } : {}),
        } as Attributes,
      ),
    getPlace: (id) =>
      recordOperation(
        'detail',
        (span) => service.getPlace(id, traceContextForSpan(span)),
        (place) => (place ? 'success' : 'not_found'),
      ),
    listFavourites: () => service.listFavourites(),
    toggleFavourite: (id) =>
      recordOperation('favourite', (span) =>
        service.toggleFavourite(id, traceContextForSpan(span)),
      ),
    submitContribution: async (input) => {
      try {
        const result = await recordOperation(
          'contribution',
          (span) => service.submitContribution(input, traceContextForSpan(span)),
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
        await recordOperation(
          'report',
          (span) => service.submitReport(input, traceContextForSpan(span)),
          undefined,
          {
            target_type: input.targetType,
          },
        )
        recordDemoAction('report', 'success', input.targetType)
      } catch (error) {
        recordDemoAction('report', 'error', input.targetType)
        throw error
      }
    },
  }
}
