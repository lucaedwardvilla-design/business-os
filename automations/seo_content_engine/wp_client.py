"""WordPress publisher implementations.

Two paths are supported, picked per-client via `client.yaml.site.api`:

  - "rest"   (default)  REST API at /wp-json/wp/v2/ using Application Password Basic auth.
                        Standard for self-hosted / Kinsta / SiteGround / IONOS Webhosting.
  - "xmlrpc"            XML-RPC at /xmlrpc.php using App Password.
                        Required for IONOS Managed WordPress (and others) where the
                        IONOS Essentials mu-plugin filters /wp/v2/* writes but leaves
                        XML-RPC untouched.

Both honor the same `Publisher` Protocol so engine.py is path-agnostic.
"""
from __future__ import annotations

import asyncio
import base64
import xmlrpc.client
from dataclasses import dataclass
from typing import Protocol

import httpx


class Publisher(Protocol):
    site_url: str

    async def list_recent_posts(self, limit: int = 20) -> list[dict]: ...
    async def create_draft(self, *, title: str, slug: str, content_html: str,
                           excerpt: str, categories: list[int] | list[str] | None = None,
                           tags: list[int] | list[str] | None = None,
                           meta: dict | None = None) -> dict: ...
    async def publish(self, post_id: int) -> dict: ...
    async def update(self, post_id: int, **fields) -> dict: ...
    async def ensure_category(self, name: str, slug: str) -> int | str: ...
    async def preview_url(self, post_id: int) -> str: ...


# ---------------------------------------------------------------------------
# REST implementation
# ---------------------------------------------------------------------------

@dataclass
class WordPressPublisher:
    """REST-based publisher (preferred when the host doesn't filter /wp/v2)."""
    site_url: str
    user: str
    app_password: str
    timeout: float = 30.0

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.user}:{self.app_password}".encode("utf-8")
        ).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    @property
    def api(self) -> str:
        return f"{self.site_url}/wp-json/wp/v2"

    async def list_recent_posts(self, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                f"{self.api}/posts",
                params={"per_page": limit, "status": "publish",
                        "_fields": "id,slug,title,link,excerpt"},
                headers=self._auth_header(),
            )
            r.raise_for_status()
            return r.json()

    async def create_draft(self, *, title: str, slug: str, content_html: str,
                           excerpt: str, categories: list[int] | list[str] | None = None,
                           tags: list[int] | list[str] | None = None,
                           meta: dict | None = None) -> dict:
        payload: dict = {
            "title": title,
            "slug": slug,
            "content": content_html,
            "excerpt": excerpt,
            "status": "draft",
        }
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        if meta:
            payload["meta"] = meta

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.api}/posts",
                json=payload,
                headers={**self._auth_header(), "Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    async def publish(self, post_id: int) -> dict:
        return await self.update(post_id, status="publish")

    async def update(self, post_id: int, **fields) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.api}/posts/{post_id}",
                json=fields,
                headers={**self._auth_header(), "Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    async def ensure_category(self, name: str, slug: str) -> int:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                f"{self.api}/categories",
                params={"slug": slug},
                headers=self._auth_header(),
            )
            r.raise_for_status()
            existing = r.json()
            if existing:
                return existing[0]["id"]

            r = await client.post(
                f"{self.api}/categories",
                json={"name": name, "slug": slug},
                headers={**self._auth_header(), "Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()["id"]

    async def preview_url(self, post_id: int) -> str:
        return f"{self.site_url}/?p={post_id}&preview=true"


# ---------------------------------------------------------------------------
# XML-RPC implementation
# ---------------------------------------------------------------------------

@dataclass
class WordPressXMLRPCPublisher:
    """XML-RPC publisher.

    Required for hosts that filter the /wp/v2/* REST namespace (notably IONOS
    Managed WordPress, where the IONOS Essentials mu-plugin blocks REST writes
    via user_has_cap filters that don't touch XML-RPC).

    Auth: App Password (created via wp-admin → Profile → Application Passwords).
    Sync xmlrpc.client wrapped in asyncio.to_thread so the engine remains async.
    """
    site_url: str
    user: str
    app_password: str
    blog_id: int = 1                # multisite "blog ID" — 1 for single-site

    @property
    def _server(self) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(
            f"{self.site_url}/xmlrpc.php", allow_none=True, use_builtin_types=True,
        )

    def _call(self, method_name: str, *args):
        """Run an authenticated XML-RPC call. Always prefixes blog_id + creds."""
        method = self._server
        for part in method_name.split("."):
            method = getattr(method, part)
        try:
            return method(self.blog_id, self.user, self.app_password, *args)
        except xmlrpc.client.Fault as e:
            raise RuntimeError(
                f"XML-RPC fault: code={e.faultCode} message={e.faultString!r}"
            ) from e

    @staticmethod
    def _post_to_rest_shape(p: dict) -> dict:
        """Translate XML-RPC post struct to the engine's REST-style dict."""
        return {
            "id": int(p.get("post_id", 0)),
            "slug": p.get("post_name", ""),
            "title": {"rendered": p.get("post_title", "")},
            "link": p.get("link", ""),
            "excerpt": {"rendered": p.get("post_excerpt", "")},
            "status": p.get("post_status", ""),
            "date": p.get("post_date", ""),
        }

    async def list_recent_posts(self, limit: int = 20) -> list[dict]:
        filt = {"post_type": "post", "post_status": "publish", "number": limit}

        def _list() -> list[dict]:
            posts = self._call("wp.getPosts", filt)
            return [self._post_to_rest_shape(p) for p in posts]

        return await asyncio.to_thread(_list)

    async def create_draft(self, *, title: str, slug: str, content_html: str,
                           excerpt: str, categories: list[int] | list[str] | None = None,
                           tags: list[int] | list[str] | None = None,
                           meta: dict | None = None) -> dict:
        struct: dict = {
            "post_type": "post",
            "post_status": "draft",
            "post_title": title,
            "post_name": slug,
            "post_content": content_html,
            "post_excerpt": excerpt,
        }
        terms_names: dict = {}
        if categories:
            terms_names["category"] = [str(c) for c in categories]
        if tags:
            terms_names["post_tag"] = [str(t) for t in tags]
        if terms_names:
            struct["terms_names"] = terms_names
        if meta:
            struct["custom_fields"] = [
                {"key": k, "value": v} for k, v in meta.items()
            ]

        def _create() -> dict:
            post_id = self._call("wp.newPost", struct)
            post_id = int(post_id)
            created = self._call("wp.getPost", post_id)
            return self._post_to_rest_shape(created)

        return await asyncio.to_thread(_create)

    async def publish(self, post_id: int) -> dict:
        return await self.update(post_id, status="publish")

    async def update(self, post_id: int, **fields) -> dict:
        struct: dict = {}
        # Translate REST field names to XML-RPC struct keys
        if "status" in fields:
            struct["post_status"] = fields["status"]
        if "title" in fields:
            struct["post_title"] = fields["title"]
        if "content" in fields:
            struct["post_content"] = fields["content"]
        if "slug" in fields:
            struct["post_name"] = fields["slug"]
        if "excerpt" in fields:
            struct["post_excerpt"] = fields["excerpt"]

        def _update() -> dict:
            self._call("wp.editPost", int(post_id), struct)
            updated = self._call("wp.getPost", int(post_id))
            return self._post_to_rest_shape(updated)

        return await asyncio.to_thread(_update)

    async def ensure_category(self, name: str, slug: str) -> str:
        """Get-or-create category. Returns the slug (XML-RPC accepts terms_names)."""
        def _ensure() -> str:
            try:
                terms = self._call("wp.getTerms", "category", {"slug": slug})
                if terms:
                    return terms[0].get("name", name)
            except RuntimeError:
                pass
            try:
                self._call("wp.newTerm", {
                    "name": name, "slug": slug, "taxonomy": "category",
                })
            except RuntimeError:
                pass
            return name

        return await asyncio.to_thread(_ensure)

    async def preview_url(self, post_id: int) -> str:
        return f"{self.site_url}/?p={post_id}&preview=true"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_publisher(*, site_url: str, user: str, app_password: str,
                   api: str = "rest") -> Publisher:
    """Pick a publisher by `api` value from client.yaml.

    "rest"   → WordPressPublisher (default for new clients on standard hosts)
    "xmlrpc" → WordPressXMLRPCPublisher (IONOS Managed and similar)
    """
    api = (api or "rest").lower()
    if api == "xmlrpc":
        return WordPressXMLRPCPublisher(
            site_url=site_url.rstrip("/"), user=user, app_password=app_password,
        )
    if api == "rest":
        return WordPressPublisher(
            site_url=site_url.rstrip("/"), user=user, app_password=app_password,
        )
    raise ValueError(f"Unsupported api={api!r} (expected 'rest' or 'xmlrpc')")
