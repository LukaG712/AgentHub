# Agent Hub UI spec (visual redesign)

Target: a calm, minimal, Apple-like messenger for named AI teammates ("Bots"), in the style of xAI's Grok Bot desktop app. Do NOT copy Grok/xAI logos, wordmarks or the exact mascot; draw our own avatar shapes. Product name stays "Agent Hub".

Scope: visual only. Do not change API endpoints, auth, hub.yaml or backend behavior. Keep existing features working. Throw away the old navy/blue dark theme and rebuild the styling from scratch.

## Feel

Almost entirely neutral grey/white (light) or neutral charcoal (dark). Color comes only from the Bot avatars. Primary buttons are BLACK pills (white pill in dark mode), never blue. Blue is only for links and unread dots.

## Design tokens (CSS variables; light default, dark via prefers-color-scheme)

Light:
- sidebar `#f6f6f6`, main `#fcfcfc`, hairline dividers `#e8e8e8`
- selected row `#e4e4e4`, search field `#ececec`
- bot bubble `#f0f0f0`, user bubble `#111` with white text
- text `#111`, secondary text `#8a8a8e`
- link/unread `#1a5fd0`, success `#12a35f`, diff add `#1a9b4b`, diff remove `#d1304a`

Dark:
- sidebar `#1c1c1c`, main `#262626`, selected row `#2e2e2e`
- bot bubble `#343434`, search/composer field `#262626` with `#3c3c3c` border
- text `#f2f2f2`, secondary `#9a9a9a`
- user bubble `#f2f2f2` with dark text; the black button becomes white

Font: system-ui / SF Pro stack, 15px base.
Radii: rows 14px, bubbles 20-22px, composer 28px, buttons and chips 999px, cards 18px.
No heavy shadows; use hairlines instead.

## App shell

Full-viewport, two columns: sidebar `clamp(280px, 24vw, 340px)` and main. No top app bar. Thin hairline between columns.

## Sidebar

- Top row: small "+" icon button (new Bot) on the right. Below it a rounded grey search field with magnifier icon ("Search") that filters the list live.
- Bot rows (the main element): ~64px tall, rounded 14px; selected row = solid soft grey.
  - 44px avatar on the left.
  - Line 1: bot name (15px, medium) with last-activity time right-aligned in secondary text ("8:20 AM", "Yesterday", "9/1").
  - Line 2: one-line last-message preview in secondary text, ellipsized.
  - Unread = small blue dot on the right of line 2.
  - Needs-approval or failed = small colored badge dot on the avatar's top-right corner.
- Small grey section labels between groups (e.g. "Working", "Recent"; later "Daily / Every week / Unassigned" once routines exist), optional count at the right.
- Bottom area: "Marketplace" row (icon in a white circle + label), "Skills" row the same way, and a profile row (round avatar + name). No emoji; use consistent line-icon SVGs.

## Avatars (our own set)

Generate as inline SVG:
- 8 geometric blob shapes: circle, wide oval, rounded square, pill, rounded triangle, hexagon, cloud, droplet.
- 10-color palette: brown `#8c5a35`, red `#f0243a`, orange `#f97316`, amber `#fbab18`, green `#16c26a`, teal `#13b9a8`, blue `#1a7cff`, purple `#9a5cf5`, pink `#ff3d9a`, grey `#727272`.
- A tiny friendly face of two small white round dot-eyes near the top (simple round dots, not slanted marks).
- Shape and color are derived from the bot, or chosen in the New Bot page and stored per bot (in agent metadata if the API supports it, otherwise in localStorage keyed by bot name).
- Group threads use a small overlapping cluster of 2-3 mini avatars.

## Thread header

Thin bar (~56px) with a hairline underneath: small avatar + bot name (medium weight) on the left; on the right two quiet icon buttons: share (disabled placeholder) and a monitor icon that toggles the right panel.

## Messages

- ~28px side padding; whole content capped at ~980px wide and centered on very wide screens.
- Bot messages: left-aligned soft grey rounded bubbles, max ~82% width, markdown rendered (lists, code blocks with copy button, links in blue).
- My messages: right-aligned black pill-ish bubbles with white text, max ~70% width.
- Centered grey timestamps between groups ("Today 8:20 AM", "Yesterday 8:22 PM").
- Centered grey system lines for events ("Renamed to X", "Created routine ⏱ Name", "Messages from ● Bot A and ● Bot B" with colored dots and names).
- Run card (a bot message):
  - Title on the left, status pill on the right (green dot + "Done", amber "Working", red "Failed").
  - Muted meta lines below (branch/path with small icon, "± N files changed +x -y" with green/red numbers if available, elapsed time).
  - Collapsible log.
  - Action buttons: black pill primary (e.g. "View result"), outlined pill secondary, and a Stop button while running.
- Smooth auto-scroll, with a "jump to latest" pill when scrolled up.

## Composer

Floating rounded card (28px radius, hairline border, white / `#262626`) spanning the thread width with ~24px side margins and a bottom margin.
- Left: circular grey "+" button (disabled placeholder).
- Placeholder: "Message <bot name>".
- Right: circular light-grey mic button (disabled placeholder) and a circular BLACK send button with an up-arrow (turns into a stop square while running).
- Textarea auto-grows; Enter sends, Shift+Enter newline.

## New Bot page (replaces the old dialog; shown in the main area)

- Header "New Bot".
- Centered: large 100px avatar preview; a row of 10 color swatches (selected = ring); a row of 8 shape buttons; a rounded "Name" input; a second input "What should this Bot do?" (our existing description/guidelines draft); a black pill "Get started" (disabled grey until a name is entered).
- Below: "Suggestions" label and 2-column cards (avatar icon + title + one-line description, e.g. "Night Shift", "Inbox Triage", "Vault Librarian"). Clicking a card fills the form fields (real behavior, no fake data).
- Runner/project_dir fields go in a collapsed "Advanced" section. The runner command is never editable.

## Marketplace / Skills pages

Large modal or page: title, "N installed" row with overlapping small icons, rounded search field, category chips (bordered pills), "Featured" section with "View all", two-column list items (icon tile, name, one-line description, grey pill "Add"). The Skills page uses the same list-item pattern with on/off toggles per bot. Unbuilt marketplace content stays an honest empty state ("Coming soon"), not fake entries.

## Right panel

Slides in from the right as a clean inspector with the same grey/hairline styling and collapsible sections: About, Skills, Memory, Routines, Plugins, Run history. Unbuilt ones show a quiet "Coming soon".

## API key screen

Centered screen: wordmark "Agent Hub", a one-line tagline, a rounded input for the key, and a black pill "Sign in →".

## Responsive

Under 800px the sidebar becomes a slide-over drawer, the right panel a bottom sheet, and the composer stays pinned at the bottom.

## Constraints

- Offline only: no external fonts, CDNs or URLs.
- Minimal dependencies; ask before adding any.
- Accessibility basics: focus rings, aria labels, sufficient contrast.

## Working method

Work in two passes and commit between them.
- Pass 1: tokens, shell, sidebar, avatars, thread header.
- Pass 2: messages, run cards, composer, New Bot page, marketplace/skills, right panel, API key screen, dark mode, responsive.

When finished, run `python -m pytest tests/ -v`, start the app, and compare it against the spec; fix anything that still looks like a default template.
