import type { SourceLicense } from '../api/types'

const LABELS: Record<SourceLicense, string> = {
  public_domain: 'public domain',
  in_copyright: 'in copyright',
  proprietary: 'proprietary',
}

export default function LicenseBadge({ license }: { license: SourceLicense }) {
  return <span className={`badge badge-${license}`}>{LABELS[license]}</span>
}
