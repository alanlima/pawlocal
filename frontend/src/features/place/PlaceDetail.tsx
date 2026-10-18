import { ArrowLeft, ArrowUpRight, Heart, MapPin, Plus, Share2 } from 'lucide-react'
import type { ContributionKind, Place, PlaceCategory } from '../../types/place'
import { PlaceArtwork } from './PlaceArtwork'

const categoryName: Record<PlaceCategory, string> = {
  dog_park: 'Dog park',
  beach: 'Beach',
  walk: 'Walk',
  hiking_area: 'Hiking area',
  cafe: 'Dog-friendly café',
}
type Props = {
  place: Place
  saved: boolean
  signedIn: boolean
  onBack: () => void
  onSave: () => void
  onShare: () => void
  onContribute: (kind: ContributionKind) => void
  onReport: (targetType: 'place' | 'contribution') => void
}

export function PlaceDetail({
  place,
  saved,
  signedIn,
  onBack,
  onSave,
  onShare,
  onContribute,
  onReport,
}: Props) {
  const rating = place.averageRating
  const hasReviewCount = place.reviewCount !== null
  const hasFacilities = place.facilities.length > 0
  return (
    <main className="detail-page">
      <button className="back-link" onClick={onBack}>
        <ArrowLeft size={17} /> All places
      </button>
      <PlaceArtwork
        place={place}
        categoryLabel={categoryName[place.category]}
        coordinates={`PAWLOCAL FIELD NOTES · ${place.area.toUpperCase()}`}
        detail
      />
      <div className="detail-layout">
        <article className="detail-main">
          <div className="place-area">
            <MapPin size={14} />
            {place.area}, South East Queensland
          </div>
          <h1>{place.name}</h1>
          <p className="detail-address">{place.address ?? 'Address not yet confirmed'}</p>
          <p className="detail-description">
            {place.description ?? 'A description has not yet been added.'}
          </p>
          {place.dogAccessRules ? (
            <div className="detail-rule">
              <div className="rule-icon">✓</div>
              <div>
                <strong>Dog access information</strong>
                <p>{place.dogAccessRules}</p>
              </div>
            </div>
          ) : (
            <div className="detail-rule">
              <div className="rule-icon">i</div>
              <div>
                <strong>Dog access details are unconfirmed</strong>
                <p>
                  We don’t have verified access rules for this place yet. Check local signage before
                  visiting.
                </p>
              </div>
            </div>
          )}
          <section className="detail-section">
            <div className="detail-section-head">
              <h2>Good to know</h2>
              <span>Verified details only</span>
            </div>
            {hasFacilities ? (
              <ul className="facility-list">
                {place.facilities.map((facility) => (
                  <li key={facility}>{facility}</li>
                ))}
              </ul>
            ) : (
              <div className="unknown-box">
                <span className="unknown-mark">?</span>
                <div>
                  <strong>Facility details are unknown</strong>
                  <p>We don’t have verified facility information for this place yet.</p>
                </div>
              </div>
            )}
            <button className="text-button contribute-inline" onClick={() => onContribute('tip')}>
              <Plus size={15} /> Add a helpful tip
            </button>
          </section>
          <section className="detail-section reviews-section">
            <div className="detail-section-head">
              <h2>Local love</h2>
              <span>
                {hasReviewCount
                  ? `${place.reviewCount} ${place.reviewCount === 1 ? 'review' : 'reviews'}`
                  : 'Review count not provided'}
              </span>
            </div>
            {rating !== null ? (
              <div className="review-summary">
                <span className="review-big">{rating.toFixed(1)}</span>
                <span
                  className="rating-stars"
                  role="img"
                  aria-label={`${rating.toFixed(1)} out of 5 stars`}
                >
                  <span
                    className="rating-stars-fill"
                    style={{ width: `${Math.max(0, Math.min(100, (rating / 5) * 100))}%` }}
                  >
                    ★★★★★
                  </span>
                  <span aria-hidden="true">★★★★★</span>
                </span>
                <span className="review-sub">
                  Community rating{place.reviewCount === null ? '' : ' · demo data'}
                </span>
              </div>
            ) : (
              <p className="empty-review">
                No rating has been provided. Be the first to share your experience.
              </p>
            )}
            <button className="outline-button" onClick={() => onContribute('review')}>
              <Plus size={15} /> Write a review
            </button>
          </section>
        </article>
        <aside className="detail-aside">
          <div className="aside-card">
            <span className="aside-kicker">SAVE FOR LATER</span>
            <h3>Keep this one close.</h3>
            <p>Your favourite spots, all in one place.</p>
            <button
              className={saved ? 'primary-button saved-action' : 'primary-button'}
              onClick={onSave}
            >
              <Heart size={16} fill={saved ? 'currentColor' : 'none'} />
              {saved ? 'Saved to your list' : 'Save this place'}
            </button>
            {!signedIn && (
              <span className="aside-hint">Sign in required · Demo mode available</span>
            )}
            <button className="outline-button share-action" onClick={onShare}>
              <Share2 size={15} /> Share this place
            </button>
          </div>
          <button className="report-link" onClick={() => onReport('place')}>
            Something not right? <span>Report this listing ↗</span>
          </button>
          <button
            className="report-link contribution-report-link"
            onClick={() => onReport('contribution')}
          >
            Report a community contribution ↗
          </button>
        </aside>
      </div>
      <div className="detail-next">
        <span>KNOW THIS PLACE?</span>
        <p>Good local knowledge makes every visit better.</p>
        <button onClick={() => onContribute('correction')}>
          Suggest an update <ArrowUpRight size={15} />
        </button>
      </div>
    </main>
  )
}
