"""Kemono, Coomer, and Pawchive API v1 calls."""

import time
from urllib.parse import quote

import requests

from kcdl.http import API_HEADERS, ApiError, Pace


def _segment(value):
    return quote(str(value), safe="")


class Api:
    def __init__(self, session, interval=0.4):
        self.session = session
        self.pace = Pace(interval)

    def profile(self, site, service, user_id):
        url = f"{site.api_root}/{_segment(service)}/user/{_segment(user_id)}/profile"
        data = self._json(url)
        if not isinstance(data, dict):
            raise ApiError(f"Profile response was not an object: {url}")
        return data

    def posts_page(self, site, service, user_id, offset):
        url = f"{site.api_root}/{_segment(service)}/user/{_segment(user_id)}/posts"
        data = self._json(url, params={"o": int(offset)})
        if isinstance(data, dict):
            data = data.get("posts") or data.get("results") or []
        if not isinstance(data, list):
            raise ApiError(f"Posts response was not a list: {url}")
        return data

    def post(self, site, service, user_id, post_id):
        url = (
            f"{site.api_root}/{_segment(service)}/user/{_segment(user_id)}"
            f"/post/{_segment(post_id)}"
        )
        data = self._json(url)
        if isinstance(data, dict) and "post" not in data and "id" in data:
            return {"post": data, "videos": [], "previews": [], "attachments": []}
        if not isinstance(data, dict) or "post" not in data:
            raise ApiError(f"Post response was missing the post object: {url}")
        return data

    def _json(self, url, params=None):
        last_error = None
        for attempt in range(4):
            self.pace.wait()
            try:
                response = self.session.get(
                    url,
                    headers=API_HEADERS,
                    params=params,
                    timeout=(15, 45),
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(8, 2 ** attempt))
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = ApiError(f"HTTP {response.status_code} for {url}")
                response.close()
                time.sleep(min(8, 2 ** attempt))
                continue
            if response.status_code >= 400:
                detail = " ".join(response.text[:180].split())
                raise ApiError(f"HTTP {response.status_code} for {url}: {detail}")
            try:
                return response.json()
            except ValueError as exc:
                raise ApiError(f"Response was not JSON: {url}") from exc
        raise ApiError(f"Request failed for {url}: {last_error}")
