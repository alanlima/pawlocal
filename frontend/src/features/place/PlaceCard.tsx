import { ArrowUpRight, Heart, MapPin, Star } from 'lucide-react'
import type { Place, PlaceCategory } from '../../types/place'
import { PlaceArtwork } from './PlaceArtwork'

const categoryName: Record<PlaceCategory, string> = {
  dog_park: 'Dog park',
  beach: 'Beach',
  walk: 'Walk',
  hiking_area: 'Hiking area',
  cafe: 'Dog-friendly café',
}
type Props = { place: Place; index: number; saved: boolean; onOpen: () => void; onSave: () => void }

export function PlaceCard({ place, index, saved, onOpen, onSave }: Props) {
  return (
    <article className="place-card" style={{ animationDelay: `${index * 55}ms` }}>
      <button className="card-art-button" onClick={onOpen} aria-label={`View ${place.name}`}>
        <PlaceArtwork
          place={place}
          categoryLabel={categoryName[place.category]}
          coordinates="SEQ · AU"
        />
      </button>
      <button
        className={saved ? 'save-button is-saved' : 'save-button'}
        aria-label={saved ? `Remove ${place.name} from saved places` : `Save ${place.name}`}
        onClick={onSave}
      >
        <Heart size={18} fill={saved ? 'currentColor' : 'none'} />
      </button>
      <button className="card-content" onClick={onOpen}>
        <span className="place-area">
          <MapPin size={13} />
          {place.area}
        </span>
        <span className="place-name">{place.name}</span>
        <span className="place-meta">
          <span>
            <Star size={14} fill="currentColor" /> {place.averageRating?.toFixed(1) ?? 'New'}{' '}
            {place.reviewCount !== null && place.reviewCount > 0 && (
              <span className="review-count">({place.reviewCount})</span>
            )}{' '}
            {place.reviewCount !== null && place.reviewCount > 0 && <small>sample</small>}
          </span>
          <span className="view-link">
            Explore <ArrowUpRight size={14} />
          </span>
        </span>
      </button>
    </article>
  )
}
