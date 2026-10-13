"""Anki add-on that exposes a small offline-review API for the Xteink X4."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import anki.lang
from anki.cards import Card
from anki.collection import OpChanges
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
)
from anki.scheduler.v3 import CardAnswer
from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QAction, QTimer, qconnect
from aqt.utils import showInfo

from .protocol import (
    PULL_NDJSON_MIME,
    FlagUpdate,
    ProtocolError,
    PushBatch,
    Review,
    encode_pull_ndjson,
    parse_push_payload,
)
from . import textutil
from .mdns_advertise import MdnsAdvertiser


ADDON_VERSION = "2.5.1"
PROTOCOL_VERSION = 3
# Hard safety caps; config and pull query params are clamped to these.
MAX_CARDS_PER_DECK_LIMIT = 1000
MAX_TOTAL_PULL_CARDS_LIMIT = 1000
LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "bind_address": "0.0.0.0",
    "port": 5050,
    # LAN discovery (mDNS/Bonjour): X4 can find this Mac without typing the IP.
    "mdns_enabled": True,
    "mdns_name": "Xteink Anki",
    "api_token": "",
    # Soft defaults; X4 may override per pull via ?max_cards=&max_total=
    "max_cards": 250,
    "max_total_cards": 1000,
    "max_text_chars": 4096,
    "max_reviews_per_push": 500,
    "max_request_bytes": 262144,
    "operation_timeout_seconds": 60,
    "sync_after_push": True,
    "allow_legacy_csv": True,
    "cors_allowed_origin": "*",
    "processed_batch_ids": [],
}

TRANSLATIONS = {
    "en": {
        "menu_action": "Xteink Status",
        "status_title": "Xteink API",
        "status_running": (
            "The Xteink API is running.\n\n"
            "Address: {address}\n"
            "Port: {port}\n"
            "API token: {token}\n"
            "Collection ready: {ready}"
        ),
        "status_stopped": "The Xteink API could not be started:\n{error}",
        "yes": "yes",
        "no": "no",
    },
    "de": {
        "menu_action": "Xteink Status",
        "status_title": "Xteink API",
        "status_running": (
            "Die Xteink API läuft.\n\n"
            "Adresse: {address}\n"
            "Port: {port}\n"
            "API-Token: {token}\n"
            "Sammlung bereit: {ready}"
        ),
        "status_stopped": "Die Xteink API konnte nicht gestartet werden:\n{error}",
        "yes": "ja",
        "no": "nein",
    },
    "el": {
        "menu_action": "Κατάσταση Xteink",
        "status_title": "Xteink API",
        "status_running": (
            "Το Xteink API εκτελείται.\n\n"
            "Διεύθυνση: {address}\n"
            "Θύρα: {port}\n"
            "API token: {token}\n"
            "Συλλογή έτοιμη: {ready}"
        ),
        "status_stopped": "Δεν ήταν δυνατή η εκκίνηση του Xteink API:\n{error}",
        "yes": "ναι",
        "no": "όχι",
    },
}

_CARD_TYPE_NAMES = {
    int(CARD_TYPE_NEW): "new",
    int(CARD_TYPE_LRN): "learning",
    int(CARD_TYPE_REV): "review",
    int(CARD_TYPE_RELEARNING): "relearning",
}


class CollectionUnavailable(RuntimeError):
    pass


class OperationTimedOut(RuntimeError):
    pass


@dataclass
class ApplyResult:
    changes: OpChanges
    processed: int
    rejected: List[Dict[str, Any]]
    sync_requested: bool = False
    sync_reason: str = ""

    def response_payload(self, batch: PushBatch) -> Dict[str, Any]:
        return {
            "status": "success" if not self.rejected else "partial",
            "protocol_version": PROTOCOL_VERSION,
            "batch_id": batch.batch_id,
            "batch_id_derived": batch.derived_batch_id,
            "legacy_csv": batch.legacy_csv,
            "processed": self.processed,
            "rejected": self.rejected,
            "sync_requested": self.sync_requested,
            "sync_reason": self.sync_reason,
        }


def _t(key: str, **kwargs: Any) -> str:
    language = getattr(anki.lang, "current_lang", "en")
    base_language = str(language).replace("_", "-").split("-", 1)[0]
    strings = TRANSLATIONS.get(base_language, TRANSLATIONS["en"])
    text = strings.get(key, TRANSLATIONS["en"].get(key, f"[{key}]"))
    return text.format(**kwargs) if kwargs else text


def _deck_display_name(full_name: str) -> str:
    """Human-readable deck path for the device list (keep hierarchy, stay compact)."""
    name = (full_name or "").strip()
    if not name:
        return "Anki"
    # Anki uses :: for nesting; show a lighter separator on the device.
    name = name.replace("::", " / ")
    # Device clips around 64 chars; keep a little headroom for UTF-8.
    if len(name) > 60:
        name = "…" + name[-59:]
    return name


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def _int_config(config: Dict[str, Any], key: str) -> int:
    fallback = int(DEFAULT_CONFIG[key])
    try:
        return int(config.get(key, fallback))
    except (TypeError, ValueError):
        LOGGER.warning("Invalid %s in Xteink config; using %s", key, fallback)
        return fallback


def _note_fields(card: Card, text_limit: int) -> Dict[str, str]:
    try:
        note = card.note()
        model = note.note_type()
        pairs: List[Tuple[str, str]] = []
        for index, field_def in enumerate(model["flds"]):
            raw = note.fields[index] if index < len(note.fields) else ""
            pairs.append((field_def["name"], raw))
        return textutil.field_map_from_pairs(pairs, limit=text_limit)
    except Exception:
        LOGGER.exception(
            "Could not read note fields for card %s", getattr(card, "id", "?")
        )
        return {}


def _template_meta(card: Card) -> Tuple[str, str, int]:
    try:
        note = card.note()
        model = note.note_type()
        ord_ = int(card.ord)
        templates = model.get("tmpls") or []
        template_name = ""
        if 0 <= ord_ < len(templates):
            template_name = str(templates[ord_].get("name") or "")
        return template_name, str(model.get("name") or ""), ord_
    except Exception:
        return "", "", int(getattr(card, "ord", 0) or 0)


def _render_card_html(card: Card) -> Tuple[str, str]:
    """Return raw question/answer HTML, preferring render_output when available."""

    try:
        if hasattr(card, "render_output"):
            output = card.render_output(reload=True)
            question_html = getattr(output, "question_text", None) or ""
            answer_html = getattr(output, "answer_text", None) or ""
            # Some Anki builds expose question/answer with CSS wrappers instead.
            if not question_html and hasattr(output, "question_and_style"):
                question_html = output.question_and_style()
            if not answer_html and hasattr(output, "answer_and_style"):
                answer_html = output.answer_and_style()
            if question_html or answer_html:
                return str(question_html or ""), str(answer_html or "")
    except Exception:
        LOGGER.exception(
            "render_output failed for card %s; falling back to question()/answer()",
            getattr(card, "id", "?"),
        )

    try:
        return str(card.question() or ""), str(card.answer() or "")
    except Exception:
        LOGGER.exception(
            "question()/answer() failed for card %s", getattr(card, "id", "?")
        )
        return "", ""


def _card_side_texts(card: Card, text_limit: int) -> Tuple[str, str]:
    """Build front/back text that stays readable on the X4 even with odd templates."""

    question_html, answer_html = _render_card_html(card)
    # XFD converter: HTML/Markdown subset → e-ink plain text (tables, lists, …).
    rendered_front = textutil.to_device_text(question_html, limit=text_limit)
    rendered_back = textutil.to_device_text(
        textutil.answer_only(answer_html), limit=text_limit
    )
    if not rendered_back:
        # Some templates put the whole card in answer(); strip the front part if present.
        full_answer = textutil.to_device_text(answer_html, limit=text_limit)
        if rendered_front and full_answer.startswith(rendered_front):
            rendered_back = full_answer[len(rendered_front) :].lstrip("\n ").strip()
        else:
            rendered_back = full_answer

    fields = _note_fields(card, text_limit)
    template_name, note_type_name, ord_ = _template_meta(card)
    reverse = textutil.looks_reversed_template(template_name, note_type_name, ord_)
    front, back = textutil.combine_sides(
        rendered_front,
        rendered_back,
        fields,
        text_limit=text_limit,
        reverse=reverse,
    )

    if front == textutil.EMPTY_SIDE_PLACEHOLDER or back == textutil.EMPTY_SIDE_PLACEHOLDER:
        LOGGER.warning(
            "Card %s still weak after fallbacks (front=%r back=%r fields=%s tmpl=%r)",
            getattr(card, "id", "?"),
            front,
            back,
            list(fields.keys()),
            template_name,
        )
    return front, back


def _local_ipv4_addresses() -> List[str]:
    addresses = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


class XteinkHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: Tuple[str, int], addon: "XteinkAddon") -> None:
        self.addon = addon
        super().__init__(server_address, XteinkAPIHandler)


class XteinkAPIHandler(BaseHTTPRequestHandler):
    server_version = f"XteinkSync/{ADDON_VERSION}"
    protocol_version = "HTTP/1.1"

    @property
    def addon(self) -> "XteinkAddon":
        return self.server.addon  # type: ignore[attr-defined]

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format_string: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], format_string % args)

    def _path(self) -> str:
        path = urlsplit(self.path).path.rstrip("/")
        return path or "/"

    def _cors_headers(self) -> Dict[str, str]:
        configured = str(self.addon.config.get("cors_allowed_origin", "")).strip()
        request_origin = self.headers.get("Origin", "")
        if not configured:
            return {}
        if configured == "*":
            return {"Access-Control-Allow-Origin": "*"}
        if request_origin == configured:
            return {
                "Access-Control-Allow-Origin": configured,
                "Vary": "Origin",
            }
        return {}

    def _send_json(
        self,
        status: int,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for name, value in self._cors_headers().items():
            self.send_header(name, value)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("Client disconnected before receiving the response")

    def _send_pull(self, payload: Dict[str, Any]) -> None:
        accepted = self.headers.get("Accept", "")
        accepted_types = {
            item.partition(";")[0].strip().lower()
            for item in accepted.split(",")
        }
        if PULL_NDJSON_MIME not in accepted_types:
            self._send_json(200, payload)
            return

        encoded = encode_pull_ndjson(payload)
        self.send_response(200)
        self.send_header("Content-Type", f"{PULL_NDJSON_MIME}; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for name, value in self._cors_headers().items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("Client disconnected before receiving the pull response")

    def _error(self, status: int, code: str, message: str) -> None:
        self._send_json(
            status,
            {
                "status": "error",
                "error": code,
                "message": message,
                "protocol_version": PROTOCOL_VERSION,
            },
        )

    def _authenticated(self) -> bool:
        expected = self.addon.api_token
        authorization = self.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        else:
            supplied = self.headers.get("X-Xteink-Token", "").strip()
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def _require_authentication(self) -> bool:
        if self._authenticated():
            return True
        self._error(401, "unauthorized", "A valid Xteink API token is required")
        return False

    def _handle_operation_error(self, error: Exception) -> None:
        if isinstance(error, CollectionUnavailable):
            self._error(503, "collection_unavailable", str(error))
        elif isinstance(error, OperationTimedOut):
            self._error(504, "operation_timeout", str(error))
        else:
            LOGGER.exception("Unhandled Xteink API error", exc_info=error)
            self._error(500, "internal_error", "The Anki operation failed")

    def do_OPTIONS(self) -> None:
        if self._path() not in {"/pull", "/push", "/health"}:
            self._error(404, "not_found", "Unknown endpoint")
            return
        self._send_json(
            200,
            {"status": "ok", "protocol_version": PROTOCOL_VERSION},
            {
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": (
                    "Authorization, Content-Type, X-Xteink-Token, "
                    "X-Xteink-Batch-ID"
                ),
                "Access-Control-Max-Age": "600",
            },
        )

    def do_GET(self) -> None:
        path = self._path()
        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "protocol_version": PROTOCOL_VERSION,
                    "addon_version": ADDON_VERSION,
                    "collection_ready": self.addon.collection_ready(),
                    "server_time": int(time.time()),
                },
            )
            return

        if path != "/pull":
            self._error(404, "not_found", "Unknown endpoint")
            return
        if not self._require_authentication():
            return

        try:
            query = parse_qs(urlsplit(self.path).query)
            max_cards = self._optional_query_int(query, "max_cards")
            max_total = self._optional_query_int(query, "max_total")
            self._send_pull(
                self.addon.pull_cards(
                    max_cards_per_deck=max_cards,
                    max_total_cards=max_total,
                )
            )
        except Exception as error:
            self._handle_operation_error(error)

    def _optional_query_int(
        self, query: Dict[str, List[str]], key: str
    ) -> Optional[int]:
        values = query.get(key) or query.get(key.replace("_", "-"))
        if not values:
            return None
        try:
            return int(values[0])
        except (TypeError, ValueError):
            return None

    def do_POST(self) -> None:
        if self._path() != "/push":
            self._error(404, "not_found", "Unknown endpoint")
            return
        if not self._require_authentication():
            return
        if self.headers.get("Transfer-Encoding"):
            self._error(400, "unsupported_transfer_encoding", "Use Content-Length")
            return

        content_length_value = self.headers.get("Content-Length")
        if content_length_value is None:
            self._error(411, "length_required", "Content-Length is required")
            return
        try:
            content_length = int(content_length_value)
        except ValueError:
            self._error(400, "invalid_content_length", "Invalid Content-Length")
            return

        max_bytes = _int_config(self.addon.config, "max_request_bytes")
        if content_length < 1:
            self._error(400, "empty_body", "Request body must not be empty")
            return
        if content_length > max_bytes:
            self._error(
                413,
                "payload_too_large",
                f"Request body exceeds {max_bytes} bytes",
            )
            return

        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self._error(400, "incomplete_body", "Request body ended unexpectedly")
            return

        try:
            batch = parse_push_payload(
                body=body,
                content_type=self.headers.get("Content-Type", "text/csv"),
                header_batch_id=self.headers.get("X-Xteink-Batch-ID"),
                max_reviews=_int_config(
                    self.addon.config, "max_reviews_per_push"
                ),
                allow_legacy_csv=bool(
                    self.addon.config.get("allow_legacy_csv", True)
                ),
            )
        except ProtocolError as error:
            self._error(error.status, error.code, error.message)
            return

        claim = self.addon.claim_batch(batch.batch_id)
        if claim == "duplicate":
            self._send_json(
                200,
                {
                    "status": "duplicate",
                    "protocol_version": PROTOCOL_VERSION,
                    "batch_id": batch.batch_id,
                    "processed": 0,
                    "rejected": [],
                    "sync_requested": False,
                },
            )
            return
        if claim == "pending":
            self._error(409, "batch_pending", "This batch is already being processed")
            return

        try:
            result = self.addon.apply_reviews(batch)
            self._send_json(200, result.response_payload(batch))
        except Exception as error:
            self._handle_operation_error(error)


class XteinkAddon:
    def __init__(self) -> None:
        loaded = mw.addonManager.getConfig(__name__) or {}
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(loaded)
        # Persist any new default keys (e.g. max_total_cards) so they appear
        # in Tools → Add-ons → Config.
        missing_defaults = [key for key in DEFAULT_CONFIG if key not in loaded]
        if missing_defaults:
            mw.addonManager.writeConfig(__name__, self.config)

        token = str(self.config.get("api_token", "")).strip()
        if not token:
            token = secrets.token_urlsafe(32)
            self.config["api_token"] = token
            mw.addonManager.writeConfig(__name__, self.config)
        elif len(token) < 16:
            LOGGER.warning("The configured Xteink API token is shorter than 16 characters")
        self.api_token = token

        processed = self.config.get("processed_batch_ids", [])
        self._processed_batch_ids = [
            item for item in processed if isinstance(item, str)
        ][-100:]
        self._pending_batch_ids = set()  # type: set[str]
        self._batch_lock = threading.Lock()

        self.httpd = None  # type: Optional[XteinkHTTPServer]
        self.server_thread = None  # type: Optional[threading.Thread]
        self.start_error = ""
        self._mdns = MdnsAdvertiser()

    def collection_ready(self) -> bool:
        return getattr(mw, "col", None) is not None

    def start_server(self) -> None:
        if self.httpd or self.server_thread:
            return

        address = str(self.config.get("bind_address", "0.0.0.0")).strip()
        port = _int_config(self.config, "port")

        def run() -> None:
            try:
                self.httpd = XteinkHTTPServer((address, port), self)
                LOGGER.info("Xteink API listening on %s:%s", address, port)
                self._start_mdns(port)
                self.httpd.serve_forever(poll_interval=0.25)
            except Exception as error:
                self.start_error = str(error)
                LOGGER.exception("Could not start the Xteink API")
            finally:
                self._mdns.stop()
                if self.httpd:
                    self.httpd.server_close()
                self.httpd = None

        self.server_thread = threading.Thread(
            target=run,
            name="xteink-http-server",
            daemon=True,
        )
        self.server_thread.start()

    def _wait_for_future(self, future: Future) -> Any:
        timeout = _int_config(self.config, "operation_timeout_seconds")
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            raise OperationTimedOut(
                f"Anki did not finish the operation within {timeout} seconds"
            )

    def pull_cards(
        self,
        max_cards_per_deck: Optional[int] = None,
        max_total_cards: Optional[int] = None,
    ) -> Dict[str, Any]:
        limits = self._resolve_pull_limits(max_cards_per_deck, max_total_cards)
        result = Future()

        def start_query() -> None:
            if not self.collection_ready():
                result.set_exception(
                    CollectionUnavailable("No Anki collection is currently open")
                )
                return

            operation = QueryOp(
                parent=mw,
                op=lambda col: self._collect_due_cards(col, limits),
                success=result.set_result,
            )
            operation.failure(result.set_exception).run_in_background()

        mw.taskman.run_on_main(start_query)
        cards, decks = self._wait_for_future(result)
        return {
            "status": "success",
            "protocol_version": PROTOCOL_VERSION,
            "pull_id": uuid.uuid4().hex,
            "server_time": int(time.time()),
            "decks": decks,
            "cards": cards,
            "max_cards": limits[0],
            "max_total_cards": limits[1],
        }

    def _resolve_pull_limits(
        self,
        max_cards_per_deck: Optional[int],
        max_total_cards: Optional[int],
    ) -> Tuple[int, int]:
        default_per_deck = _int_config(self.config, "max_cards")
        default_total = _int_config(self.config, "max_total_cards")
        per_deck = default_per_deck if max_cards_per_deck is None else max_cards_per_deck
        total = default_total if max_total_cards is None else max_total_cards
        per_deck = _clamp_int(per_deck, 1, MAX_CARDS_PER_DECK_LIMIT)
        total = _clamp_int(total, 1, MAX_TOTAL_PULL_CARDS_LIMIT)
        # Per-deck cannot usefully exceed the total budget.
        per_deck = min(per_deck, total)
        return per_deck, total

    def _collect_due_cards(
        self, collection: Any, limits: Tuple[int, int]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        max_cards_per_deck, max_total_cards = limits
        text_limit = max(128, _int_config(self.config, "max_text_chars"))
        original_deck_id = collection.decks.get_current_id()

        try:
            # Deepest decks first; pure parent folders are skipped (children cover them).
            study_decks = self._due_study_decks(collection)
            payload: List[Dict[str, Any]] = []
            seen_card_ids: set[int] = set()
            deck_counts: Dict[str, Dict[str, Any]] = {}

            deck_count = max(1, len(study_decks))
            # Fair share so one large stack cannot starve the rest of the pull.
            fair_share = max(
                1,
                min(max_cards_per_deck, max_total_cards // deck_count),
            )

            for study_deck_id, study_deck_name, child_due in study_decks:
                remaining_budget = max_total_cards - len(payload)
                if remaining_budget <= 0:
                    break

                collection.decks.select(study_deck_id)
                # Parent queues interleave subdeck cards; over-fetch then keep only
                # cards whose home deck is this study deck (children already pulled).
                fetch_limit = min(
                    remaining_budget,
                    max(fair_share, max_cards_per_deck) + max(0, int(child_due)),
                )
                if fetch_limit <= 0:
                    break

                try:
                    queued_cards = collection.sched.get_queued_cards(
                        fetch_limit=fetch_limit
                    ).cards
                except Exception:
                    LOGGER.exception(
                        "get_queued_cards failed for deck %s (%s)",
                        study_deck_id,
                        study_deck_name,
                    )
                    continue

                accepted_for_deck = 0
                for queued_card in queued_cards:
                    if accepted_for_deck >= max_cards_per_deck:
                        break
                    if len(payload) >= max_total_cards:
                        break

                    try:
                        card_id = int(queued_card.card.id)
                    except Exception:
                        card = Card(collection, backend_card=queued_card.card)
                        card_id = int(card.id)
                    if card_id in seen_card_ids:
                        continue

                    try:
                        card = collection.get_card(card_id)
                    except Exception:
                        card = Card(collection, backend_card=queued_card.card)

                    try:
                        home_deck_id = int(card.did)
                    except Exception:
                        home_deck_id = int(study_deck_id)

                    # Only keep cards that live in this study deck. When a parent
                    # is selected, subdeck cards are skipped (already handled as leaves).
                    if home_deck_id != int(study_deck_id):
                        continue

                    seen_card_ids.add(card_id)
                    try:
                        home_deck_name = collection.decks.name(home_deck_id)
                    except Exception:
                        home_deck_name = study_deck_name or str(home_deck_id)
                    display_name = _deck_display_name(home_deck_name)

                    card_type = int(card.type)
                    front_text, back_text = _card_side_texts(card, text_limit)
                    deck_key = str(home_deck_id)
                    # deck_id / deck_name first so embedded clients see titles even if a
                    # later field is dropped under memory pressure when parsing the line.
                    try:
                        card_flag = int(getattr(card, "flags", 0) or 0)
                    except Exception:
                        card_flag = 0
                    if card_flag < 0 or card_flag > 7:
                        card_flag = 0

                    payload.append(
                        {
                            "id": str(card_id),
                            "deck_id": deck_key,
                            "deck_name": display_name,
                            "front": front_text,
                            "back": back_text,
                            "flag": card_flag,
                            "card_type": _CARD_TYPE_NAMES.get(card_type, "unknown"),
                            # Kept for compatibility with the original X4 client.
                            "is_learning": card_type
                            in {
                                int(CARD_TYPE_NEW),
                                int(CARD_TYPE_LRN),
                                int(CARD_TYPE_RELEARNING),
                            },
                            "queue": int(card.queue),
                            "reps": int(card.reps),
                            "mod": int(card.mod),
                        }
                    )
                    accepted_for_deck += 1
                    summary = deck_counts.get(deck_key)
                    if summary is None:
                        deck_counts[deck_key] = {
                            "id": deck_key,
                            "name": display_name,
                            "card_count": 1,
                        }
                    else:
                        summary["card_count"] = int(summary["card_count"]) + 1

            decks_summary = list(deck_counts.values())
            LOGGER.info(
                "Xteink pull: %s cards across %s decks (study units=%s)",
                len(payload),
                len(decks_summary),
                len(study_decks),
            )
            return payload, decks_summary
        finally:
            try:
                collection.decks.select(original_deck_id)
            except Exception:
                LOGGER.exception("Could not restore the previously selected Anki deck")

    def _due_study_decks(
        self, collection: Any
    ) -> List[Tuple[int, str, int]]:
        """Due study units deepest-first: (deck_id, name, child_due_sum).

        Pure parent folders (due only from children) are skipped so each leaf
        becomes its own selectable stack. Parents that still have own due cards
        (total due > sum of children) remain included.
        """

        study_decks: List[Tuple[int, str, int]] = []

        def due_count(node: Any) -> int:
            return (
                int(getattr(node, "review_count", 0) or 0)
                + int(getattr(node, "learn_count", 0) or 0)
                + int(getattr(node, "new_count", 0) or 0)
            )

        def walk(node: Any) -> None:
            children = list(getattr(node, "children", None) or [])
            for child in children:
                walk(child)

            total_due = due_count(node)
            if total_due <= 0:
                return

            child_due = sum(due_count(child) for child in children)
            # Anki tree counts are cumulative (self + children). Skip pure folders.
            if children and total_due <= child_due:
                return

            deck_id = int(node.deck_id)
            if deck_id == 0:
                return
            try:
                deck_name = collection.decks.name(deck_id)
            except Exception:
                deck_name = str(getattr(node, "name", "") or deck_id)
            if not deck_name:
                return
            study_decks.append((deck_id, deck_name, child_due))

        try:
            root = collection.sched.deck_due_tree()
        except Exception:
            LOGGER.exception("Could not read Anki's deck due tree")
            root = None

        if root is not None:
            walk(root)
            if study_decks:
                return study_decks

        # Fallback: current deck only (legacy behaviour).
        current_id = int(collection.decks.get_current_id())
        return [(current_id, collection.decks.name(current_id), 0)]

    def claim_batch(self, batch_id: str) -> str:
        with self._batch_lock:
            if batch_id in self._processed_batch_ids:
                return "duplicate"
            if batch_id in self._pending_batch_ids:
                return "pending"
            self._pending_batch_ids.add(batch_id)
            return "claimed"

    def release_batch(self, batch_id: str) -> None:
        with self._batch_lock:
            self._pending_batch_ids.discard(batch_id)

    def _complete_batch(self, batch_id: str) -> None:
        with self._batch_lock:
            self._pending_batch_ids.discard(batch_id)
            self._processed_batch_ids = [
                item for item in self._processed_batch_ids if item != batch_id
            ]
            self._processed_batch_ids.append(batch_id)
            self._processed_batch_ids = self._processed_batch_ids[-100:]

        self.config["processed_batch_ids"] = list(self._processed_batch_ids)
        try:
            mw.addonManager.writeConfig(__name__, self.config)
        except Exception:
            LOGGER.exception("Could not persist processed Xteink batch IDs")

    def apply_reviews(self, batch: PushBatch) -> ApplyResult:
        result = Future()

        def fail(error: Exception) -> None:
            self.release_batch(batch.batch_id)
            result.set_exception(error)

        def succeeded(apply_result: ApplyResult) -> None:
            self._complete_batch(batch.batch_id)
            (
                apply_result.sync_requested,
                apply_result.sync_reason,
            ) = self._request_ankiweb_sync(apply_result.processed)
            result.set_result(apply_result)

        def start_operation() -> None:
            if not self.collection_ready():
                fail(CollectionUnavailable("No Anki collection is currently open"))
                return

            operation = CollectionOp(
                parent=mw,
                op=lambda collection: self._apply_batch(collection, batch),
            )
            operation.success(succeeded).failure(fail).run_in_background(
                initiator=self
            )

        mw.taskman.run_on_main(start_operation)
        return self._wait_for_future(result)

    def _apply_batch(self, collection: Any, batch: PushBatch) -> ApplyResult:
        aggregate_changes = OpChanges()
        rejected = []
        processed = 0

        for index, review in enumerate(batch.reviews):
            try:
                changes = self._answer_card(collection, review)
                aggregate_changes.MergeFrom(changes)
                processed += 1
            except Exception as error:
                LOGGER.exception(
                    "Could not grade Xteink card %s", review.card_id
                )
                rejected.append(
                    {
                        "index": index,
                        "card_id": str(review.card_id),
                        "error": str(error),
                        "kind": "review",
                    }
                )

        for index, flag_update in enumerate(batch.flags):
            try:
                changes = self._set_card_flag(collection, flag_update)
                if changes is not None:
                    try:
                        aggregate_changes.MergeFrom(changes)
                    except Exception:
                        pass
                processed += 1
            except Exception as error:
                LOGGER.exception(
                    "Could not set Xteink flag on card %s", flag_update.card_id
                )
                rejected.append(
                    {
                        "index": index,
                        "card_id": str(flag_update.card_id),
                        "error": str(error),
                        "kind": "flag",
                    }
                )

        return ApplyResult(
            changes=aggregate_changes,
            processed=processed,
            rejected=rejected,
        )

    def _set_card_flag(self, collection: Any, flag_update: FlagUpdate) -> Any:
        """Set Anki user flag 0–7 on a card (0 clears)."""
        flag = int(flag_update.flag)
        if flag < 0 or flag > 7:
            raise ValueError(f"flag must be 0–7, got {flag}")

        # Prefer bulk helper when available (Anki 2.1.50+).
        if hasattr(collection, "set_user_flag_for_cards"):
            return collection.set_user_flag_for_cards(flag, [flag_update.card_id])

        card = collection.get_card(flag_update.card_id)
        if hasattr(card, "set_user_flag"):
            card.set_user_flag(flag)
        else:
            card.flags = flag
        if hasattr(collection, "update_card"):
            return collection.update_card(card)
        if hasattr(card, "flush"):
            card.flush()
        return OpChanges()

    def _answer_card(self, collection: Any, review: Review) -> OpChanges:
        card = collection.get_card(review.card_id)
        card.start_timer()
        if review.duration_ms:
            card.timer_started = time.time() - (review.duration_ms / 1000)

        scheduler = collection.sched
        if all(
            hasattr(scheduler, attribute)
            for attribute in ("build_answer", "answer_card")
        ):
            rating = {
                1: CardAnswer.AGAIN,
                2: CardAnswer.HARD,
                3: CardAnswer.GOOD,
                4: CardAnswer.EASY,
            }[review.ease]
            try:
                states = collection._backend.get_scheduling_states(card.id)
                answer = scheduler.build_answer(
                    card=card,
                    states=states,
                    rating=rating,
                )
                if review.answered_at_ms is not None:
                    answer.answered_at_millis = review.answered_at_ms
                answer.milliseconds_taken = review.duration_ms
                return scheduler.answer_card(answer)
            except Exception as error:
                # Offline batches are often not in Anki's live queue order.
                # v3 answer_card then raises "not at top of queue"; legacy
                # answerCard still applies the grade to that card id.
                message = str(error).lower()
                if "not at top of queue" not in message:
                    LOGGER.warning(
                        "Falling back to Anki's legacy answerCard() API for card %s",
                        review.card_id,
                        exc_info=True,
                    )
                else:
                    LOGGER.info(
                        "Card %s not at top of queue; using legacy answerCard()",
                        review.card_id,
                    )

        return scheduler.answerCard(card, review.ease)

    def _request_ankiweb_sync(self, processed: int) -> Tuple[bool, str]:
        if not processed:
            return False, "no_changes"
        if not bool(self.config.get("sync_after_push", True)):
            return False, "disabled"
        if not mw.pm.sync_auth():
            return False, "not_logged_in"
        if mw.media_syncer.is_syncing():
            return False, "already_syncing"

        QTimer.singleShot(0, mw.on_sync_button_clicked)
        return True, "scheduled"

    def _start_mdns(self, port: int) -> None:
        enabled = bool(self.config.get("mdns_enabled", True))
        name = str(self.config.get("mdns_name", "Xteink Anki") or "Xteink Anki")
        try:
            self._mdns.start(
                port,
                enabled=enabled,
                instance_name=name,
                protocol_version=PROTOCOL_VERSION,
                addon_version=ADDON_VERSION,
            )
        except Exception:
            LOGGER.exception("mDNS advertise failed")

    def stop_server(self) -> None:
        """Stop HTTP + mDNS (profile close / unload)."""
        self._mdns.stop()
        httpd = self.httpd
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                LOGGER.exception("Could not shut down Xteink HTTP server")

    def show_status(self) -> None:
        if self.start_error:
            message = _t("status_stopped", error=self.start_error)
        else:
            configured_address = str(
                self.config.get("bind_address", "0.0.0.0")
            ).strip()
            addresses = _local_ipv4_addresses()
            display_address = (
                ", ".join(addresses)
                if configured_address == "0.0.0.0" and addresses
                else configured_address
            )
            port = _int_config(self.config, "port")
            message = _t(
                "status_running",
                address=display_address,
                port=port,
                token=self.api_token,
                ready=_t("yes") if self.collection_ready() else _t("no"),
            )
            if self._mdns.active:
                message += (
                    f"\n\nmDNS: _xteink-anki._tcp  port {port}"
                    f"  ({self._mdns.backend})"
                )
            elif bool(self.config.get("mdns_enabled", True)):
                message += (
                    "\n\nmDNS: not advertising "
                    "(dns-sd/zeroconf unavailable — set the server URL manually on the device)"
                )
        showInfo(message, title=_t("status_title"))


addon = XteinkAddon()

action = QAction(_t("menu_action"), mw)
qconnect(action.triggered, addon.show_status)
mw.form.menuTools.addAction(action)

gui_hooks.main_window_did_init.append(addon.start_server)


def _xteink_stop_server() -> None:
    addon.stop_server()


# Unregister mDNS when Anki profile closes so stale LAN records disappear.
if hasattr(gui_hooks, "profile_will_close"):
    gui_hooks.profile_will_close.append(_xteink_stop_server)
