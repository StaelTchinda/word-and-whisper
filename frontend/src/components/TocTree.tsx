import { Link } from 'react-router'
import type { TocResponse, TocSubsection as TocSubsectionType } from '../api/types'

function countItems(sub: TocSubsectionType): number {
  return sub.items.length + sub.children.reduce((n, c) => n + countItems(c), 0)
}

function Subsection({ sourceId, sub }: { sourceId: string; sub: TocSubsectionType }) {
  const n = countItems(sub)
  return (
    <details className="toc-subsection">
      <summary>
        {sub.label} <span className="item-count">({n})</span>
      </summary>
      {sub.book_section_id && (
        <p className="toc-empty-section">
          {sub.items.length === 0 && sub.children.length === 0 && 'No prayers recorded here. '}
          <Link to={`/sources/${sourceId}/book-sections/${sub.book_section_id}`}>
            Book introduction →
          </Link>
        </p>
      )}
      {sub.items.length > 0 && (
        <ul className="toc-items">
          {sub.items.map((item) => (
            <li key={item.id}>
              <Link to={`/sources/${sourceId}/${item.id}`}>
                <span>{item.title ?? item.ref_display}</span>
                {item.title && <span className="ref">{item.ref_display}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {sub.children.map((child) => (
        <Subsection sourceId={sourceId} sub={child} key={child.id} />
      ))}
    </details>
  )
}

export default function TocTree({ sourceId, toc }: { sourceId: string; toc: TocResponse }) {
  return (
    <div className="toc">
      {toc.sections.map((section, index) => (
        <details className="toc-section" key={section.id} open={index === 0}>
          <summary>{section.label}</summary>
          {section.subsections.map((sub) => (
            <Subsection sourceId={sourceId} sub={sub} key={sub.id} />
          ))}
        </details>
      ))}
    </div>
  )
}
