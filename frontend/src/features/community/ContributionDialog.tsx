import { useEffect, useRef, type KeyboardEvent } from 'react'
import { ArrowUpRight, Star, X } from 'lucide-react'
import type { Contribution, ContributionKind } from '../../types/place'

type Props = {
  dialog: 'contribute' | 'report' | null
  signedIn: boolean
  setSignedIn: (value: boolean) => void
  kind: ContributionKind
  setKind: (value: ContributionKind) => void
  rating: number
  setRating: (value: number) => void
  message: string
  setMessage: (value: string) => void
  writeError: string
  reportTargetType: 'place' | 'contribution'
  reportTargetId: string
  reportPlaceId: string
  reportableContributions: Contribution[]
  setReportTargetType: (value: 'place' | 'contribution') => void
  setReportTargetId: (value: string) => void
  onClose: () => void
  onSubmit: () => void
  onNotice: (message: string) => void
}

export function ContributionDialog({
  dialog,
  signedIn,
  setSignedIn,
  kind,
  setKind,
  rating,
  setRating,
  message,
  setMessage,
  writeError,
  reportTargetType,
  reportTargetId,
  reportPlaceId,
  reportableContributions,
  setReportTargetType,
  setReportTargetId,
  onClose,
  onSubmit,
  onNotice,
}: Props) {
  const dialogRef = useRef<HTMLElement>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const focusNoteAfterSignIn = useRef(false)
  useEffect(() => {
    if (dialog) dialogRef.current?.querySelector<HTMLElement>('[data-dialog-entry]')?.focus()
  }, [dialog])
  useEffect(() => {
    if (signedIn && focusNoteAfterSignIn.current) {
      focusNoteAfterSignIn.current = false
      noteRef.current?.focus()
    }
  }, [signedIn])
  if (!dialog) return null
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = [
      ...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]',
      ) ?? []),
    ]
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }
  const validReportId =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      reportTargetId.trim(),
    )
  const canSubmit = !!message.trim() && (dialog !== 'report' || validReportId)
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="modal"
        ref={dialogRef}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <button className="modal-close" data-dialog-entry onClick={onClose} aria-label="Close">
          <X size={19} />
        </button>
        <div className="section-kicker">
          {dialog === 'report' ? 'HELP KEEP IT TRUSTWORTHY' : 'A COMMUNITY BUILT WITH CARE'}
        </div>
        <h2 id="modal-title">
          {dialog === 'report' ? 'Tell us what’s wrong' : 'Share what you know'}
          <span className="heading-dot">.</span>
        </h2>
        {!signedIn && (
          <div className="modal-note flex flex-col gap-2">
            <span>You’re in visitor mode. Demo contributions require a member state.</span>
            <button
              className="inline-flex items-center rounded border border-stone-300 bg-white px-3 py-2 text-sm text-green-800"
              onClick={() => {
                focusNoteAfterSignIn.current = true
                setSignedIn(true)
                onNotice('You are signed in as a demo member.')
              }}
            >
              Continue as demo member
            </button>
          </div>
        )}
        {dialog === 'report' && (
          <>
            <label className="form-label">
              What are you reporting?
              <select
                value={reportTargetType}
                onChange={(event) => {
                  const type = event.target.value as 'place' | 'contribution'
                  setReportTargetType(type)
                  setReportTargetId(
                    type === 'place' ? reportPlaceId : (reportableContributions[0]?.id ?? ''),
                  )
                }}
              >
                <option value="place">A place listing</option>
                <option value="contribution">A community contribution</option>
              </select>
            </label>
            {reportTargetType === 'contribution' &&
              (reportableContributions.length ? (
                <>
                  <label className="form-label">
                    Choose a community contribution
                    <select
                      value={reportTargetId}
                      onChange={(event) => setReportTargetId(event.target.value)}
                    >
                      {reportableContributions.map((contribution) => (
                        <option key={contribution.id} value={contribution.id}>
                          {contribution.demoOnly ? '[Demo only] ' : ''}
                          {contribution.body}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="modal-note" role="note">
                    {reportableContributions.find(
                      (contribution) => contribution.id === reportTargetId,
                    )?.demoOnly
                      ? 'DEMO ONLY — this example is synthetic and is not community data.'
                      : 'Selected contribution'}
                  </p>
                </>
              ) : (
                <p className="modal-note" role="status">
                  No published community contributions are available to report yet.
                </p>
              ))}
          </>
        )}
        {dialog === 'contribute' && (
          <label className="form-label">
            What would you like to share?
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as ContributionKind)}
            >
              <option value="review">A review</option>
              <option value="location_suggestion">Suggest a place</option>
              <option value="tip">A useful tip</option>
              <option value="correction">A correction</option>
            </select>
          </label>
        )}
        {dialog === 'contribute' && kind === 'review' && (
          <div className="form-label">
            <span>Your rating</span>
            <div className="flex gap-1" role="group" aria-label="Your rating">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  type="button"
                  key={value}
                  className={`grid place-items-center border-0 bg-transparent p-1 ${value <= rating ? 'text-amber-600' : 'text-stone-400'}`}
                  aria-label={`Rate ${value} star${value === 1 ? '' : 's'}`}
                  aria-pressed={rating === value}
                  onClick={() => setRating(value)}
                >
                  <Star size={21} fill={value <= rating ? 'currentColor' : 'none'} />
                </button>
              ))}
            </div>
          </div>
        )}
        <label className="form-label">
          {dialog === 'report' ? 'What should our community team check?' : 'Your note'}
          <textarea
            ref={noteRef}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder={
              dialog === 'report'
                ? 'Share the details so we can look into it…'
                : 'Share helpful, firsthand details…'
            }
            rows={4}
            maxLength={2000}
          />
        </label>
        {writeError && (
          <p className="form-error text-sm text-red-700" role="alert">
            {writeError}
          </p>
        )}
        <div className="modal-actions">
          <button className="text-button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-button" disabled={!canSubmit} onClick={onSubmit}>
            {dialog === 'report' ? 'Send report' : 'Share with PawLocal'} <ArrowUpRight size={15} />
          </button>
        </div>
      </section>
    </div>
  )
}
