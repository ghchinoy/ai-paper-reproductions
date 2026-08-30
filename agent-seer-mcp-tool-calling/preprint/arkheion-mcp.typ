// arkheion-mcp.typ - House style wrapper for academic preprints
// Inspired by NeurIPS/Google Research (e.g. WikiSkill) clean booktabs typography

#import "@preview/arkheion:0.1.2": arkheion as base-arkheion, arkheion-appendices
#import "@preview/cetz:0.3.4"

// Accent palette
#let accent-amber = rgb("#FDE293")
#let accent-amber-subtle = rgb("#FEF3C7")
#let accent-blue = rgb("#2563EB")
#let accent-gray-bg = rgb("#F8FAFC")
#let accent-gray-border = rgb("#E2E8F0")

// Highlight helper for key methods / results
#let row-highlight(content) = text(weight: "bold", fill: rgb("#92400E"))[#content]
#let badge-highlight(content) = box(
  fill: accent-amber,
  inset: (x: 3.5pt, y: 1.5pt),
  radius: 2pt,
  baseline: 0%,
  outset: 0pt,
)[#text(size: 0.85em, weight: "bold", fill: rgb("#78350F"))[#content]]

#let preprint-theme(
  title: "",
  abstract: none,
  keywords: (),
  authors: (),
  date: none,
  body,
) = {
  // Apply base arkheion layout
  show: base-arkheion.with(
    title: title,
    abstract: abstract,
    keywords: keywords,
    authors: authors,
    date: date,
  )

  // Configure typography & spacing
  set text(font: "New Computer Modern", size: 10pt)
  set par(justify: true, leading: 0.65em)

  // Table styling: compact booktabs theme (no vertical grid lines, compact font)
  show table: set text(size: 8.2pt)
  set table(
    stroke: none,
    fill: none,
    inset: (x: 4.5pt, y: 3.5pt),
  )

  // Figure captions: bold supplement and counter, clean compact text
  show figure.caption: it => {
    block(
      width: 100%,
      above: 0.8em,
      below: 0.8em,
      align(center)[
        #text(size: 8.8pt)[
          #strong(it.supplement + " " + context it.counter.display()): #it.body
        ]
      ]
    )
  }

  // Code blocks: clean framed container
  show raw.where(block: true): it => {
    block(
      width: 100%,
      fill: accent-gray-bg,
      stroke: 0.5pt + accent-gray-border,
      radius: 3pt,
      inset: (x: 8pt, y: 6pt),
      text(size: 8.2pt, it)
    )
  }

  body
}

// Native grouped bar chart for Nanobanana baseline vs enriched TC scores
#let nanobanana-chart() = {
  let cases = (
    ("NB0", 1.000, 0.989),
    ("NB1", 0.944, 0.778),
    ("NB2", 0.767, 0.778),
    ("NB3", 0.906, 0.750),
    ("NB4", 0.794, 0.667),
    ("NB5", 0.817, 0.806),
    ("NB6", 1.000, 1.000),
    ("NB7", 0.822, 0.900),
  )

  let c-baseline = rgb("#64748B") // slate gray
  let c-enriched = rgb("#D97706") // warm amber / gold (house accent)

  cetz.canvas({
    import cetz.draw: *

    let w = 1.2
    let gap = 0.35
    let bar-w = 0.42
    let max-h = 3.5 // maps to 1.0 score

    // Y-axis gridlines and labels
    for y-val in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0) {
      let y-pos = y-val * max-h
      line((0, y-pos), (cases.len() * (w + gap) + 0.1, y-pos), stroke: (paint: rgb("#E2E8F0"), dash: "dotted", thickness: 0.5pt))
      content((-0.35, y-pos), text(size: 7.2pt, fill: rgb("#64748B"))[#calc.round(y-val, digits: 1)])
    }

    // Y-axis title
    content((-0.9, max-h / 2), angle: 90deg, text(size: 8pt, weight: "bold", fill: rgb("#334155"))[Tool-Calling Score ($"TC"$)])

    // X-axis baseline
    line((0, 0), (cases.len() * (w + gap) + 0.1, 0), stroke: 0.8pt + rgb("#94A3B8"))

    // Plot bars
    for (i, (label, base, enrich)) in cases.enumerate() {
      let x-center = 0.3 + i * (w + gap)
      let x-base = x-center
      let x-enrich = x-center + bar-w

      let h-base = base * max-h
      let h-enrich = enrich * max-h

      // Baseline bar
      rect((x-base, 0), (x-base + bar-w, h-base), fill: c-baseline, stroke: 0.3pt + c-baseline.darken(20%))
      // Enriched bar
      rect((x-enrich, 0), (x-enrich + bar-w, h-enrich), fill: c-enriched, stroke: 0.3pt + c-enriched.darken(20%))

      // X-axis label
      content((x-center + bar-w, -0.3), text(size: 7.5pt, weight: "bold", fill: rgb("#1E293B"))[#label])
    }

    // Legend below chart (centered)
    let legend-y = -0.85
    let legend-x = 3.5
    rect((legend-x - 1.6, legend-y - 0.08), (legend-x - 1.25, legend-y + 0.12), fill: c-baseline, stroke: 0.3pt + c-baseline.darken(20%))
    content((legend-x, legend-y + 0.02), text(size: 7.8pt)[Baseline (Schema-Blind)])

    rect((legend-x + 2.1, legend-y - 0.08), (legend-x + 2.45, legend-y + 0.12), fill: c-enriched, stroke: 0.3pt + c-enriched.darken(20%))
    content((legend-x + 4.3, legend-y + 0.02), text(size: 7.8pt, weight: "bold")[Enriched (Capability Matrix)])
  })
}
