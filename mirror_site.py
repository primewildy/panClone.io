import argparse
import hashlib
import os
import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import cloudscraper
from bs4 import BeautifulSoup

ALLOWED_SCHEMES = {"http", "https"}
ASSET_TAG_ATTRS = {
    "img": ["src", "data-src", "data-original", "data-lazy-src", "data-srcset", "srcset"],
    "script": ["src"],
    "link": ["href"],
    "source": ["src", "srcset"],
    "video": ["src", "poster"],
    "audio": ["src"],
    "track": ["src"],
    "use": ["href", "xlink:href"],
}

LOCALISE_DOMAINS = {"uk.pandora.net", "cdn.media.amplience.net"}
URL_IN_STYLE_RE = re.compile(r"url\((['\"]?)(https?://[^'\"\)]+)\1\)")


def canonicalize(url: str, base: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("javascript:") or url.startswith("mailto:") or url.startswith("tel:"):
        return None
    joined = urljoin(base, url)
    parsed = urlsplit(joined)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return None
    parsed = parsed._replace(fragment="")
    return urlunsplit(parsed)


def url_to_local_path(url: str, root: Path) -> Path:
    parsed = urlsplit(url)
    netloc = parsed.netloc
    path = parsed.path
    if not path or path.endswith("/"):
        path = path.rstrip("/") + "/index.html"
    elif not Path(path).suffix:
        path = path.rstrip("/") + "/index.html"
    local_path = root / netloc / path.lstrip("/")
    if parsed.query:
        digest = hashlib.md5(parsed.query.encode()).hexdigest()[:8]
        suffix = local_path.suffix
        if suffix:
            local_path = local_path.with_suffix("")
            local_path = local_path.with_name(f"{local_path.name}_{digest}{suffix}")
        else:
            local_path = local_path / f"query_{digest}"
    return local_path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def should_localize(url: str) -> bool:
    parsed = urlsplit(url)
    domain = parsed.netloc
    return any(domain == host or domain.endswith(f".{host}") for host in LOCALISE_DOMAINS)


def localize_url(scraper, url: str, page_local: Path, asset_cache: dict[str, Path], root: Path) -> str | None:
    if not should_localize(url):
        return None
    local_path = download_binary(scraper, url, root, asset_cache)
    if not local_path:
        return None
    return os.path.relpath(local_path, page_local.parent)


def download_binary(scraper, url: str, root: Path, cache: dict[str, Path]) -> Path | None:
    if url in cache:
        return cache[url]
    try:
        resp = scraper.get(url, stream=True, timeout=30)
        resp.raise_for_status()
    except Exception:
        return None
    local_path = url_to_local_path(url, root)
    ensure_parent(local_path)
    with open(local_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                fh.write(chunk)
    cache[url] = local_path
    return local_path


def rewrite_srcset(scraper, tag, attr, page_url: str, page_local: Path, asset_cache: dict[str, Path], root: Path):
    raw = tag.get(attr)
    if not raw:
        return
    parts = []
    changed = False
    for candidate in raw.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        if " " in candidate:
            url_part, descriptor = candidate.split(" ", 1)
        else:
            url_part, descriptor = candidate, ""
        canon = canonicalize(url_part, page_url)
        if canon:
            local = download_binary(scraper, canon, root, asset_cache)
            if local:
                rel = os.path.relpath(local, page_local.parent)
                parts.append(f"{rel} {descriptor}".strip())
                changed = True
                continue
        parts.append(candidate)
    if changed:
        tag[attr] = ", ".join(parts)


def handle_asset(scraper, tag, attr, tag_name: str, page_url: str, page_local: Path, asset_cache: dict[str, Path], root: Path):
    value = tag.get(attr)
    if not value:
        return
    canon = canonicalize(value, page_url)
    if not canon:
        return
    if tag_name == "link":
        rels = {rel.lower() for rel in tag.get("rel", [])}
        if {"preconnect", "dns-prefetch"} & rels:
            tag.decompose()
            return
    local = download_binary(scraper, canon, root, asset_cache)
    if local:
        rel = os.path.relpath(local, page_local.parent)
        tag[attr] = rel


def crawl(start_url: str, output_root: Path, max_pages: int, follow_prefix: str | None):
    scraper = cloudscraper.create_scraper()
    queue: deque[str] = deque([start_url])
    visited_pages: set[str] = set()
    asset_cache: dict[str, Path] = {}

    while queue and len(visited_pages) < max_pages:
        current_url = queue.popleft()
        canon_current = canonicalize(current_url, start_url)
        if not canon_current or canon_current in visited_pages:
            continue
        print(f"Fetching: {canon_current}")
        try:
            resp = scraper.get(canon_current, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            print(f"Failed: {canon_current} -> {exc}")
            continue
        visited_pages.add(canon_current)

        soup = BeautifulSoup(resp.text, "lxml")
        for iframe in soup.find_all("iframe"):
            iframe.decompose()

        page_local = url_to_local_path(canon_current, output_root)
        ensure_parent(page_local)

        # Collect links for further crawling and rewrite anchor hrefs
        for a in soup.find_all("a"):
            href = a.get("href")
            canon_link = canonicalize(href, canon_current)
            if not canon_link:
                continue
            parsed = urlsplit(canon_link)
            if parsed.netloc.endswith("pandora.net"):
                if follow_prefix is None or parsed.path.startswith(follow_prefix):
                    if canon_link not in visited_pages:
                        queue.append(canon_link)
                local_path = url_to_local_path(canon_link, output_root)
                rel = os.path.relpath(local_path, page_local.parent)
                a["href"] = rel

        for form in soup.find_all("form"):
            action = form.get("action")
            canon_action = canonicalize(action, canon_current)
            if not canon_action:
                continue
            parsed = urlsplit(canon_action)
            if parsed.netloc.endswith("pandora.net"):
                local_path = url_to_local_path(canon_action, output_root)
                rel = os.path.relpath(local_path, page_local.parent)
                form["action"] = rel

        # Handle assets
        for tag_name, attrs in ASSET_TAG_ATTRS.items():
            for tag in soup.find_all(tag_name):
                for attr in attrs:
                    if attr in ("srcset", "data-srcset"):
                        rewrite_srcset(scraper, tag, attr, canon_current, page_local, asset_cache, output_root)
                    else:
                        handle_asset(scraper, tag, attr, tag_name, canon_current, page_local, asset_cache, output_root)

        # Inline style attributes with url()
        for tag in soup.find_all(style=True):
            style_value = tag.get("style")
            if not style_value:
                continue
            changed = False

            def replace_match(match: re.Match) -> str:
                nonlocal changed
                url = match.group(2)
                rel = localize_url(scraper, url, page_local, asset_cache, output_root)
                if rel:
                    changed = True
                    quote = match.group(1)
                    return f"url({quote}{rel}{quote})"
                return match.group(0)

            new_style = URL_IN_STYLE_RE.sub(replace_match, style_value)
            if changed:
                tag["style"] = new_style

        # <style> tag contents
        for style_tag in soup.find_all("style"):
            if not style_tag.string:
                continue
            text = style_tag.string
            changed = False

            def replace_match(match: re.Match) -> str:
                nonlocal changed
                url = match.group(2)
                rel = localize_url(scraper, url, page_local, asset_cache, output_root)
                if rel:
                    changed = True
                    quote = match.group(1)
                    return f"url({quote}{rel}{quote})"
                return match.group(0)

            updated = URL_IN_STYLE_RE.sub(replace_match, text)
            if changed:
                style_tag.string.replace_with(updated)

        # Meta tags with URLs we want to localise
        for meta in soup.find_all("meta"):
            content = meta.get("content")
            if not content or not content.startswith("http"):
                continue
            rel = localize_url(scraper, content, page_local, asset_cache, output_root)
            if rel:
                meta["content"] = rel

        html_bytes = soup.prettify("utf-8")
        with open(page_local, "wb") as fh:
            fh.write(html_bytes)

    return visited_pages


def main():
    parser = argparse.ArgumentParser(description="Static mirror via cloudscraper")
    parser.add_argument("start_url", help="Root URL to mirror")
    parser.add_argument("--output", default="site", help="Output directory")
    parser.add_argument("--max-pages", type=int, default=30, help="Maximum pages to crawl")
    parser.add_argument("--follow-prefix", default="/en/", help="Path prefix to follow for internal links")
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    visited = crawl(args.start_url, output_root, args.max_pages, args.follow_prefix)
    print(f"Downloaded {len(visited)} pages to {output_root}")


if __name__ == "__main__":
    main()
