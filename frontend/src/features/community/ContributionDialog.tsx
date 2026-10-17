import { ArrowUpRight, Star, X } from 'lucide-react'
import type { ContributionKind } from '../../types/place'

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
  onClose: () => void
  onSubmit: () => void
  onNotice: (message: string) => void
}

export function ContributionDialog({ dialog, signedIn, setSignedIn, kind, setKind, rating, setRating, message, setMessage, onClose, onSubmit, onNotice }: Props) {
  if (!dialog) return null
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <button className="modal-close" onClick={onClose} aria-label="Close"><X size={19} /></button>
      <div className="section-kicker">{dialog === 'report' ? 'HELP KEEP IT TRUSTWORTHY' : 'A COMMUNITY BUILT WITH CARE'}</div>
      <h2 id="modal-title">{dialog === 'report' ? 'Tell us what’s wrong' : 'Share what you know'}<span className="heading-dot">.</span></h2>
      {!signedIn && <div className="modal-note"><span>You’re in visitor mode. Demo contributions require a member state.</span><button className="inline-flex items-center rounded border border-stone-300 bg-white px-3 py-2 text-sm text-green-800" onClick={() => { setSignedIn(true); onNotice('You are signed in as a demo member.') }}>Continue as demo member</button></div>}
      {dialog === 'contribute' && <label className="form-label">What would you like to share?<select value={kind} onChange={(event) => setKind(event.target.value as ContributionKind)}><option value="review">A review</option><option value="location_suggestion">Suggest a place</option><option value="tip">A useful tip</option><option value="correction">A correction</option></select></label>}
      {dialog === 'contribute' && kind === 'review' && <div className="form-label"><span>Your rating</span><div className="flex gap-1" role="group" aria-label="Your rating">{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} className={`grid place-items-center border-0 bg-transparent p-1 ${value <= rating ? 'text-amber-600' : 'text-stone-400'}`} aria-label={`Rate ${value} star${value === 1 ? '' : 's'}`} aria-pressed={rating === value} onClick={() => setRating(value)}><Star size={21} fill={value <= rating ? 'currentColor' : 'none'} /></button>)}</div></div>}
      <label className="form-label">{dialog === 'report' ? 'What should our community team check?' : 'Your note'}<textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder={dialog === 'report' ? 'Share the details so we can look into it…' : 'Share helpful, firsthand details…'} rows={4} maxLength={2000} /></label>
      <div className="modal-actions"><button className="text-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={!message.trim()} onClick={onSubmit}>{dialog === 'report' ? 'Send report' : 'Share with PawLocal'} <ArrowUpRight size={15} /></button></div>
    </section>
  </div>
}
