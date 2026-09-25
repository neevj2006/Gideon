from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import requests


class WebService:
    def weather(self, location: str) -> str:
        try:
            data = requests.get(
                f"https://wttr.in/{quote_plus(location)}", params={"format": "j1"}, timeout=10
            ).json()
            current = data["current_condition"][0]
            desc = current["weatherDesc"][0]["value"]
            return f"In {location}, it is {current['temp_F']} degrees Fahrenheit and {desc.lower()}."
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise RuntimeError(f"Weather lookup failed: {exc}") from exc

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return titles and links from DuckDuckGo's HTML search results."""
        try:
            html = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Gideon/1.0 personal assistant"},
                timeout=15,
            ).text
            from html.parser import HTMLParser

            results: list[dict[str, str]] = []

            class Parser(HTMLParser):
                capture = False
                href = ""
                text = ""

                def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                    values = dict(attrs)
                    if tag == "a" and "result__a" in (values.get("class") or ""):
                        self.capture, self.href, self.text = True, values.get("href") or "", ""

                def handle_data(self, data: str) -> None:
                    if self.capture:
                        self.text += data

                def handle_endtag(self, tag: str) -> None:
                    if tag == "a" and self.capture:
                        results.append({"title": self.text.strip(), "url": self.href})
                        self.capture = False

            Parser().feed(html)
            return results[:limit]
        except requests.RequestException as exc:
            raise RuntimeError(f"Web search failed: {exc}") from exc
