# Scientific Diving Governance Map

**Open the map:** https://fabbiologia.github.io/scientific-diving-map/

This page is a searchable knowledge graph and mind map of how scientific diving is governed around the world: the laws and regulators that apply to it, the standards and national bodies, the training routes, the recognition arrangements between systems, and the live policy issues. Each entry opens a card with a summary, short facts, its connections and links to its sources, and every card leads into two documents: a condensed companion and the full evidence report.

## What it covers

The evidence was gathered from public sources in two rounds, with positions as at 12 October 2026 and 27 October 2026. It covers the United Kingdom (including agency dive teams, the Crown Dependencies and the Overseas Territories), Europe, North America, Asia and the Pacific, Africa and the Middle East, Latin America and the Caribbean, the polar programmes, international standards and treaties, and cross-cutting issues such as medical standards, recompression access, recognition and equity of access.

## How to read it

- Every claim links to its source. Claims taken from a search summary without opening the page are marked "(unverified)", and claims from a reproduction or secondary account are marked "(secondary source)".
- Dashed rings in the graph mark questions the research has not settled. "Not identified" means the research did not find it, never that a place is unregulated.
- The map is desk research of public sources, carried out with AI research agents that recorded a verification flag for each claim; it has not been proofread end to end and it is not legal advice. Check the primary text before relying on any provision.

## Using the page

- Press `/` to search the map entries and the full text of both documents.
- Switch between **Graph** and **Mind map** in the header; **Briefing** opens the talking points and **Documents** opens the reader.
- Link straight to an entry with its id after `#`, for example `#sdsc`, `#esdp`, `#romania` or `#uk-ots`; `#mindmap` and `#briefing` open those views.

## Corrections

Corrections and new sources are welcome through the repository's Issues tab. Please include the source link.

## How the page is built

`index.html` is a single self-contained file built from a node and edge list, the companion text and the full evidence report. It loads D3, marked and DOMPurify from cdnjs and fonts from Google Fonts, and needs no server code.
