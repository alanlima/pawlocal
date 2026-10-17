export type PlaceCategory = 'dog_park' | 'beach' | 'walk' | 'hiking_area' | 'cafe'
export type Facility = 'Fenced' | 'Off-leash area' | 'Drinking water' | 'Shade' | 'Picnic tables' | 'Accessible paths'
export type ContributionKind = 'review' | 'location_suggestion' | 'tip' | 'correction'

export interface Place {
  id: string
  name: string
  category: PlaceCategory
  area: string
  address: string | null
  description: string | null
  dogAccessRules: string | null
  facilities: Facility[]
  averageRating: number | null
  reviewCount: number
  sourceUpdatedAt: string | null
  imageUrl?: string
  accent: string
}

export interface PlaceQuery { q?: string; area?: string; category?: PlaceCategory | ''; facilities?: Facility[] }
export interface ContributionInput { kind: ContributionKind; placeId?: string; rating?: number; body: string }
export interface ReportInput { targetType: 'place' | 'contribution'; targetId: string; reason: string }
export interface Contribution extends ContributionInput { id: string; createdAt: string }
