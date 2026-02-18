"""Web scraping using requests and BeautifulSoup for HomeCase portal."""

import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import config

logger = logging.getLogger(__name__)

# API endpoints
HOMECASE_LOGIN_API_PATH = "/login/withEmail"
HOMECASE_BFF_API_PATH = "/api/v1/bff"

# Request configuration
REQUEST_TIMEOUT = 10
MAX_ACTIVITIES_TO_SCAN = 40
CONSUMPTION_EXTRACT_MAX_LENGTH = 3500

# Token extraction patterns
ANTIFORGERY_TOKEN_NAMES = (
    "__RequestVerificationToken",
    "RequestVerificationToken",
    "requestVerificationToken",
)
ANTIFORGERY_COOKIE_PREFIX = ".AspNetCore.Antiforgery"


class HomeCaseScraper:
    """Scraper for HomeCase portal using requests."""

    def __init__(self):
        """Initialize scraper with requests session."""
        self.session = requests.Session()
        self._last_request_ts: Optional[float] = None
        parsed = urlparse(config.HOMECASE_URL_LOGIN)
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Origin": self._base_url,
                "Connection": "keep-alive",
            }
        )

    def _throttled_request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        """Execute a request with a configured pause between requests."""
        delay_seconds = max(config.REQUEST_DELAY_SECONDS, 0.0)
        if self._last_request_ts is not None and delay_seconds > 0:
            elapsed = time.monotonic() - self._last_request_ts
            wait_time = delay_seconds - elapsed
            if wait_time > 0:
                logger.debug(
                    "Sleeping %.2fs before %s %s", wait_time, method.upper(), url
                )
                time.sleep(wait_time)

        response = self.session.request(method=method, url=url, **kwargs)
        self._last_request_ts = time.monotonic()
        return response

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.close()

    def close(self) -> None:
        """Close session."""
        self.session.close()
        logger.debug("Session closed")

    def _get_request_verification_token(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract RequestVerificationToken from login page."""
        # Preferred source: HomeCase embeds the exact token to use in requests.
        token = self._extract_window_object_string_field(
            soup, "__ANTIFORGERY_CONFIG__", "token"
        )
        if token:
            return token

        # Fallback: token from HTML input fields
        for name in ANTIFORGERY_TOKEN_NAMES:
            inp = soup.find("input", {"name": name})
            if inp and inp.get("value"):
                return inp["value"]
        # Fallback: antiforgery cookie value (ASP.NET Core stores token in cookie)
        for cookie in self.session.cookies:
            if ANTIFORGERY_COOKIE_PREFIX in cookie.name:
                return cookie.value
        return None

    def _extract_window_object_literal(
        self, soup: BeautifulSoup, variable_name: str
    ) -> Optional[str]:
        """Extract object literal from `window.<var> = {...};` script assignment."""
        pattern = re.compile(
            rf"window\.{re.escape(variable_name)}\s*=\s*(\{{.*?\}})\s*;",
            re.DOTALL,
        )
        for script in soup.find_all("script"):
            content = script.string or script.get_text() or ""
            match = pattern.search(content)
            if not match:
                continue
            return match.group(1)
        return None

    def _extract_window_object_string_field(
        self,
        soup: BeautifulSoup,
        variable_name: str,
        field_name: str,
    ) -> Optional[str]:
        """Extract string value from a JS object literal assigned to a window variable."""
        object_literal = self._extract_window_object_literal(soup, variable_name)
        if not object_literal:
            return None

        field_pattern = re.compile(
            rf"{re.escape(field_name)}\s*:\s*(null|\"((?:\\.|[^\"])*)\")",
            re.DOTALL,
        )
        match = field_pattern.search(object_literal)
        if not match:
            return None
        if match.group(1) == "null":
            return None
        raw_value = match.group(2)
        return json.loads(f'"{raw_value}"')

    def login(self) -> None:
        """Login to HomeCase portal via JSON API (POST /login/withEmail)."""
        logger.info("Fetching login page for session and antiforgery token")

        response = self._throttled_request(
            "GET",
            config.HOMECASE_URL_LOGIN,
            timeout=REQUEST_TIMEOUT,
            headers={"Referer": self._base_url + "/"},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        token = self._get_request_verification_token(soup)
        customer_token = self._extract_window_object_string_field(
            soup,
            "__INITIAL_LOGIN_DATA__",
            "customerToken",
        )
        if not token:
            raise ValueError(
                "Could not extract RequestVerificationToken from login page"
            )

        login_url = urljoin(self._base_url + "/", HOMECASE_LOGIN_API_PATH.lstrip("/"))
        payload = {
            "email": config.HOMECASE_USERNAME,
            "password": config.HOMECASE_PASSWORD,
        }
        params = {}
        if customer_token:
            params["customerToken"] = customer_token
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": config.HOMECASE_URL_LOGIN,
            "X-Requested-With": "XMLHttpRequest",
        }
        headers["RequestVerificationToken"] = token

        logger.debug("POST %s with JSON credentials", login_url)
        resp = self._throttled_request(
            "POST",
            login_url,
            params=params,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.error(
                "HomeCase login failed with HTTP %s. Response snippet: %s",
                resp.status_code,
                resp.text[:500].replace("\n", " "),
            )
            resp.raise_for_status()

        # API may return JSON with success/error
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("success") is False:
                msg = data.get("message") or data.get("error") or "Login failed"
                raise ValueError(msg)
        except requests.exceptions.JSONDecodeError:
            # Some successful login responses redirect to HTML; keep going.
            data = None

        if resp.status_code not in (200, 204):
            raise ValueError(f"Login failed with unexpected status {resp.status_code}")

        logger.info("Login successful")

    def _api_get(self, endpoint_path: str, params: Optional[dict] = None) -> Any:
        """Execute GET request against HomeCase BFF API and decode JSON."""
        api_url = urljoin(self._base_url + "/", HOMECASE_BFF_API_PATH.lstrip("/") + "/")
        full_url = urljoin(api_url, endpoint_path.lstrip("/"))
        response = self._throttled_request(
            "GET",
            full_url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": config.HOMECASE_URL_MESSAGES,
            },
        )
        response.raise_for_status()
        return response.json()

    def _extract_consumption_from_text(self, text: str) -> Optional[str]:
        """Extract consumption section from free text."""
        if "Verbrauchswerte" not in text:
            return None

        cleaned = re.sub(r"\r\n?", "\n", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # Capture from "Verbrauchswerte" to common closings if present.
        match = re.search(
            r"(Verbrauchswerte.*?)(?=\n(?:Falls Sie Fragen|Mit freundlichen|Viele Grüße|Bitte beachten)|\Z)",
            cleaned,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        idx = cleaned.lower().find("verbrauchswerte")
        if idx >= 0:
            return cleaned[idx : idx + CONSUMPTION_EXTRACT_MAX_LENGTH].strip()
        return None

    def _parse_message_url_context(self) -> Optional[tuple[str, str, Optional[str]]]:
        """Parse customer token, facility object ID, and optional activity ID from messages URL."""
        parsed_path = [
            part
            for part in urlparse(config.HOMECASE_URL_MESSAGES).path.split("/")
            if part
        ]
        # Expected path: /{customerToken}/objekte/{facilityObjectId}/nachrichten/{activityId?}
        if (
            len(parsed_path) < 4
            or parsed_path[1] != "objekte"
            or parsed_path[3] != "nachrichten"
        ):
            return None
        customer_token = parsed_path[0]
        facility_object_id = parsed_path[2]
        activity_id = parsed_path[4] if len(parsed_path) > 4 else None
        return customer_token, facility_object_id, activity_id

    def _collect_activity_ids(
        self,
        customer_token: str,
        facility_object_id: str,
        initial_activity_id: Optional[str],
    ) -> list[str]:
        """Collect activity IDs sorted newest first."""
        activity_ids: list[str] = []
        if initial_activity_id:
            activity_ids.append(initial_activity_id)

        try:
            activities = self._api_get(
                f"/customers/{customer_token}/facilityObjects/{facility_object_id}/activities",
                params={"filterType": "Default"},
            )
            if isinstance(activities, list):
                sorted_activities = sorted(
                    [a for a in activities if isinstance(a, dict)],
                    key=lambda item: item.get("changedDateUTC")
                    or item.get("createdDateUTC")
                    or "",
                    reverse=True,
                )
                for activity in sorted_activities:
                    target_id = activity.get("id")
                    if target_id and target_id not in activity_ids:
                        activity_ids.append(str(target_id))
        except requests.RequestException:
            logger.warning("Failed to fetch activities list")
        return activity_ids

    def _collect_contact_messages(
        self, customer_token: str, activity_ids: list[str]
    ) -> list[tuple[str, str]]:
        """Collect consumption messages from activity contacts."""
        candidates: list[tuple[str, str]] = []

        for activity_id in activity_ids[:MAX_ACTIVITIES_TO_SCAN]:
            try:
                contacts = self._api_get(
                    f"/customers/{customer_token}/activities/{activity_id}/contacts",
                )
                if not isinstance(contacts, list):
                    continue

                for contact in contacts:
                    if not isinstance(contact, dict):
                        continue
                    text = contact.get("text")
                    if not text:
                        continue
                    message = self._extract_consumption_from_text(str(text))
                    if message:
                        timestamp = str(
                            contact.get("createdDateUTC")
                            or contact.get("changedDateUTC")
                            or "",
                        )
                        candidates.append((timestamp, message))
            except requests.RequestException:
                logger.debug(f"Failed to fetch contacts for activity {activity_id}")
                continue

        return candidates

    def _deduplicate_and_limit(
        self, candidates: list[tuple[str, str]], limit: Optional[int]
    ) -> list[str]:
        """Deduplicate messages by normalized text and apply limit."""
        if not candidates:
            return []

        # Sort newest first by contact timestamp (ISO strings sort lexicographically)
        candidates.sort(key=lambda item: item[0], reverse=True)

        # Deduplicate by normalized message text while preserving order
        seen: set[str] = set()
        messages: list[str] = []
        for _, message in candidates:
            normalized = re.sub(r"\s+", " ", message).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            messages.append(message)
            if limit is not None and len(messages) >= limit:
                break
        return messages

    def _fetch_consumption_messages_via_api(
        self, limit: Optional[int] = None
    ) -> list[str]:
        """Fetch consumption messages via HomeCase BFF API (newest first)."""
        url_context = self._parse_message_url_context()
        if not url_context:
            logger.warning("Could not parse message URL context")
            return []

        customer_token, facility_object_id, activity_id = url_context
        activity_ids = self._collect_activity_ids(
            customer_token, facility_object_id, activity_id
        )
        candidates = self._collect_contact_messages(customer_token, activity_ids)
        return self._deduplicate_and_limit(candidates, limit)

    def _collect_html_candidates(self, soup: BeautifulSoup) -> list[str]:
        """Collect candidate text sources from HTML page."""
        candidates: list[str] = []

        # Candidate 1: full rendered page text
        page_text = soup.get_text(separator="\n", strip=True)
        if page_text:
            candidates.append(page_text)

        # Candidate 2: message-like containers
        containers = soup.find_all(
            ["div", "article", "section"],
            class_=re.compile(r"message|Message|nachricht|Nachricht|content|Content"),
        )
        for container in containers:
            text = container.get_text(separator="\n", strip=True)
            if text:
                candidates.append(text)

        # Candidate 3: embedded script payloads (common in SPA initial state)
        for script in soup.find_all("script"):
            content = script.string or script.get_text() or ""
            if "Verbrauchswerte" in content:
                normalized = content.replace("\\n", "\n")
                candidates.append(normalized)

        return candidates

    def _score_message_candidate(self, message_text: str) -> int:
        """Score a message candidate based on length and keyword presence."""
        score = len(message_text)
        for keyword in ("Kaltwasser", "Warmwasser", "Heizung"):
            if re.search(keyword, message_text, re.IGNORECASE):
                score += 500
        return score

    def _find_latest_consumption_message_from_html(self) -> Optional[str]:
        """Fallback HTML parsing for one consumption message."""
        response = self._throttled_request(
            "GET",
            config.HOMECASE_URL_MESSAGES,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        if "/anmelden" in response.url:
            raise ValueError(
                "Not authenticated: redirected to login page while loading messages"
            )

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = self._collect_html_candidates(soup)

        best_message: Optional[str] = None
        best_score = -1
        for candidate in candidates:
            message_text = self._extract_consumption_from_text(candidate)
            if not message_text:
                continue
            score = self._score_message_candidate(message_text)
            if score > best_score:
                best_score = score
                best_message = message_text

        return best_message

    def find_consumption_messages(self, limit: Optional[int] = None) -> list[str]:
        """Find consumption messages, newest first."""
        logger.info("Searching for consumption messages")

        try:
            messages = self._fetch_consumption_messages_via_api(limit=limit)
            if messages:
                logger.info(
                    "Found %d consumption message(s) via HomeCase API", len(messages)
                )
                logger.debug("Most recent message preview: %s...", messages[0][:100])
                return messages
        except requests.RequestException as exc:
            logger.warning(
                "API message fetch failed, falling back to HTML parsing: %s", exc
            )

        # Fallback to HTML scraping: best effort, usually only one message.
        message = self._find_latest_consumption_message_from_html()
        if not message:
            return []
        return [message]

    def navigate_to_messages(self) -> None:
        """Navigate to the message stream URL."""
        logger.info("Navigating to message stream")
        response = self._throttled_request(
            "GET",
            config.HOMECASE_URL_MESSAGES,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        logger.debug("Message stream page loaded")

    def find_latest_consumption_message(self) -> Optional[str]:
        """Find the most recent message containing 'Verbrauchswerte'."""
        messages = self.find_consumption_messages(limit=1)
        if not messages:
            logger.warning("No consumption message found")
            return None
        return messages[0]
