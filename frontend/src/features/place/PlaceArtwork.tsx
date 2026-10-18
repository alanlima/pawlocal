import { Mountain, Sun, TreePine, Waves } from 'lucide-react'
import type { Place } from '../../types/place'

const artwork = {
  sea: { className: 'art-sea', Icon: Waves },
  green: { className: 'art-green', Icon: TreePine },
  sand: { className: 'art-sand', Icon: Sun },
  sky: { className: 'art-sky', Icon: Mountain },
} as const

type Props = {
  place: Place
  categoryLabel: string
  coordinates: string
  detail?: boolean
}

export function PlaceArtwork({ place, categoryLabel, coordinates, detail = false }: Props) {
  const { className, Icon } = artwork[place.accent as keyof typeof artwork] ?? artwork.sky
  const ArtworkIcon = Icon

  return (
    <span className={`${detail ? 'detail-art' : 'card-art'} ${className}`}>
      <span className="art-label">{categoryLabel}</span>
      <span className="art-graphic" aria-hidden="true">
        <ArtworkIcon />
      </span>
      <span className="art-coordinates">{coordinates}</span>
    </span>
  )
}
