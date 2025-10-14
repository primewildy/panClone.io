# panClone.io

This repository powers the GitHub Pages mirror at
`https://primewildy.github.io/panClone.io`. The site includes a standalone
Pandora/YouTube Shorts player (`index2.html`) that can be customised via query
string parameters or driven by local JSON feeds generated from YouTube.

## index2.html Usage

### Base URL

```
https://primewildy.github.io/panClone.io/index2
```

### Query Parameters

- `shorts` (alias: `source`, `src`, `channel`, `url`)
  - Accepts a YouTube channel shorts URL, e.g.
    `https://www.youtube.com/@TheOfficialPandora/shorts`.
  - Accepts custom feed aliases, e.g. `shorts=ee` uses the local
    `data/ee-shorts.json` feed, while `shorts=marcopolo` resolves to the Marco
    Polo channel.
- `bg` (alias: `background`, `colour`, `color`) sets the page background colour.
  - Accepts hex formats with or without `#` (`057382`, `#057382`, `FFF`).
  - When using a local feed alias the default background can be supplied by the
    feed metadata (e.g. `ee` defaults to `#057382`).
- `ytKey` (alias: `key`, `apikey`) optionally supplies a YouTube Data API v3 key.
  - When present and the `shorts` param points at a YouTube handle, the player
    fetches shorts via the Data API instead of using the proxy.

### Examples

- Default Pandora feed:
  `https://primewildy.github.io/panClone.io/index2`
- Custom background:
  `https://primewildy.github.io/panClone.io/index2?bg=%23f0c4d5`
- Marco Polo feed with brand background:
  `https://primewildy.github.io/panClone.io/index2?shorts=marcopolo&bg=%230b1f2a`
- EE shorts from local feed:
  `https://primewildy.github.io/panClone.io/index2?shorts=ee`
- Remote channel with Data API fallback:
  `https://primewildy.github.io/panClone.io/index2?shorts=https://www.youtube.com/@EEUK/shorts&ytKey=YOUR_KEY`

## Local Shorts Feeds

Local feeds live in `data/*.json` and contain arrays of shorts such as
`data/ee-shorts.json`. Each entry follows the shape:

```json
{
  "id": "HUfONI2IjQA",
  "url": "https://www.youtube.com/shorts/HUfONI2IjQA"
}
```

When the `shorts` query resolves to a known alias the player either loads IDs
from the corresponding JSON feed (e.g. `shorts=ee`) or rewrites to a predefined
channel URL (e.g. `shorts=marcopolo`). Local feeds skip the proxy entirely. Up
to fifteen IDs are used per session.

## Scraping Shorts Feeds

The helper script `scripts/fetch_shorts.py` scrapes a shorts tab directly from
YouTube and persists the IDs in the JSON format described above. It works by
spoofing a curl user agent so YouTube serves the fully rendered HTML containing
the `ytInitialData` payload.

### Requirements

- Python 3.8+
- `requests` (install via `pip install requests` if needed)

### Usage

```bash
python scripts/fetch_shorts.py --handle @EEUK --output data/ee-shorts.json --limit 30
```

Arguments:

- `--handle` (required): Channel handle or identifier. `@` is added if missing.
- `--output` (required): Path for the generated JSON feed.
- `--limit` (optional): Maximum number of shorts to record (default `50`).

The script fails with a non-zero exit code when the page cannot be parsed or no
shorts are discovered. Regenerate and commit the JSON whenever you want to refresh
the feed served on GitHub Pages.

## Updating EE Feed

```
python scripts/fetch_shorts.py --handle @EEUK --output data/ee-shorts.json --limit 30
git add data/ee-shorts.json
git commit -m "Update EE shorts feed"
git push
```

## Notes

- Remote fetching of shorts without a Data API key uses `https://r.jina.ai/` as a
  proxy. Some channels (like EE) return regional errors via the proxy, so use the
  local feed or Data API path in those cases.
- Always keep API keys out of the repository; pass them at request time via the
  `ytKey` query parameter.
