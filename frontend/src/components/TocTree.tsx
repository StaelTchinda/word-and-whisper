import { Link } from 'react-router'
import type { TocResponse } from '../api/types'

export default function TocTree({ sourceId, toc }: { sourceId: string; toc: TocResponse }) {
  return (
    <div className="toc">
      {toc.sections.map((section, index) => (
        <details className="toc-section" key={section.id} open={index === 0}>
          <summary>{section.label}</summary>
          {section.subsections.map((sub) => (
            <details className="toc-subsection" key={sub.id}>
              <summary>
                {sub.label} <span className="item-count">({sub.items.length})</span>
              </summary>
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
            </details>
          ))}
        </details>
      ))}
    </div>
  )
}
