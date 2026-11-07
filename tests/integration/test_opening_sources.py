"""The explorer and Wikibooks behind their local store (v0.13, FR-12.2, 12.15), and the run-level cap.

Fixtures are invented, in the shape of each API, so no Wikibooks text enters this public repo (CC BY-SA), and
no real game data either."""

from __future__ import annotations

from typing import Any

import chess
import httpx
import pytest

from weaksquare.adapters.db.repos.openings import ExplorerCacheRepo, WikibooksPagesRepo
from weaksquare.adapters.db.repos.user_data import SettingsRepo
from weaksquare.adapters.http import HttpClient
from weaksquare.adapters.opening_sources import LichessExplorer, WikibooksClient
from weaksquare.core.errors import ValidationError
from weaksquare.core.opening_sources import (
    MAX_PAGE_CHARS,
    MAX_PROMPT_CHARS,
    MAX_PROMPT_PAGE_CHARS,
    WikiPage,
    clean_page,
    page_title,
    page_url,
    parse_explorer,
    parse_extract,
    prompt_text,
)
from weaksquare.services.opening_sources import OpeningSources

EXPLORER_BODY = {
    "white": 900,
    "draws": 100,
    "black": 800,
    "moves": [
        {"uci": "e7e5", "san": "e5", "white": 500, "draws": 50, "black": 450},
        {"uci": "c7c5", "san": "c5", "white": 400, "draws": 50, "black": 350},
        {"uci": "e2e4", "san": "e4", "white": 1, "draws": 1, "black": 1},  # illegal for Black: dropped
        {"uci": "nonsense", "san": "??", "white": 1, "draws": 1, "black": 1},
    ],
}
WIKI_TEXT = """== 3. Bc4 · Invented heading ==
An invented sentence about the bishop. See https://example.org/evil for more.

== Theory table ==
A table that shouldn't be kept.

=== Sub of table ===
Nor this.

== History ==
An invented history.

== References ==
A reference."""


def wiki_body(text: str = WIKI_TEXT, revid: int = 42) -> dict[str, Any]:
    return {"query": {"pages": [{"title": "x", "extract": text, "revisions": [{"revid": revid}]}]}}


class Tokens:
    def __init__(self, token: str | None = "lip_FAKE") -> None:
        self.value = token

    def token(self) -> str | None:
        return self.value


class Net:
    """A scripted network: answers by host, and records what's asked."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.explorer: Any = EXPLORER_BODY
        self.wiki: Any = wiki_body()
        self.fail: type[Exception] | None = None
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail("offline", request=request)  # type: ignore[call-arg]
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "no"})
        body = self.explorer if "explorer" in request.url.host else self.wiki
        return httpx.Response(200, json=body)


@pytest.fixture
def net() -> Net:
    return Net()


@pytest.fixture
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def sources(services: Any, clock: Any, net: Net, tokens: Tokens) -> OpeningSources:
    http = HttpClient(transport=httpx.MockTransport(net), retries=0, sleep=lambda _s: None)
    return OpeningSources(
        LichessExplorer(http), WikibooksClient(http), ExplorerCacheRepo(services.db), WikibooksPagesRepo(services.db),
        SettingsRepo(services.db), tokens, clock,
    )  # fmt: skip


AFTER_E4 = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
TITLE = page_title(["e4", "e5", "Nf3", "Nc6", "Bc4"])


# ---- Wikibooks, pure ------------------------------------------------------------------------------------


def test_a_title_follows_the_books_naming() -> None:
    assert TITLE == "Chess Opening Theory/1. e4/1...e5/2. Nf3/2...Nc6/3. Bc4"
    assert page_title([]) == "Chess Opening Theory"
    assert page_url(TITLE) == "https://en.wikibooks.org/wiki/Chess_Opening_Theory/1._e4/1...e5/2._Nf3/2...Nc6/3._Bc4"


def test_a_check_or_mate_mark_is_left_out_of_the_title_and_the_link() -> None:
    """v0.13-B20: Wikibooks names its pages without them, so a title with one finds no page."""
    assert page_url(page_title(["e4", "Qh4+"])).endswith("/1._e4/1...Qh4")
    assert page_url(page_title(["f3", "e5", "g4", "Qh4#"])).endswith("/2...Qh4")


def test_cleaning_drops_urls_and_reference_sections() -> None:
    text = clean_page(WIKI_TEXT)
    assert "example.org" not in text and "http" not in text
    assert "shouldn't be kept" not in text and "Nor this" not in text and "A reference" not in text
    assert "invented sentence" in text and "invented history" in text and "==" not in text


def test_cleaning_caps_a_long_page_and_drops_control_characters() -> None:
    assert len(clean_page(("x" * 10 + " ") * 1000)) == MAX_PAGE_CHARS
    assert "\x07" not in clean_page("a\x07b")


@pytest.mark.parametrize(
    "data",
    [
        {"query": {"pages": [{"title": "x", "missing": True}]}},
        {"query": {"pages": []}},
        {"query": {"pages": [{"title": "x", "extract": "   "}]}},
        {"nonsense": 1},
        None,
        [],
    ],
)
def test_anything_unexpected_counts_as_no_page(data: Any) -> None:
    assert parse_extract("t", data).status == "missing"


def test_a_page_keeps_its_revision() -> None:
    page = parse_extract("t", wiki_body(revid=77))
    assert page.status == "ok" and page.revision_id == 77


def test_prompt_text_respects_both_limits_and_says_what_it_used() -> None:
    big = [WikiPage(f"Chess Opening Theory/1. m{i}", "ok", i, "y" * 9000) for i in range(5)]
    text, used = prompt_text(big)
    assert text.count("y") == MAX_PROMPT_CHARS
    assert max(len(x) for x in text.split("\n\n")) <= MAX_PROMPT_PAGE_CHARS + 40
    assert [p.revision_id for p in used] == [0, 1, 2]


def test_prompt_text_skips_missing_pages() -> None:
    text, used = prompt_text([WikiPage("Chess Opening Theory/1. e4", "missing", None, "")])
    assert text == "" and used == ()


# ---- the explorer, pure --------------------------------------------------------------------------------


def test_explorer_keeps_legal_moves_most_played_first_and_rebuilds_san() -> None:
    result = parse_explorer(AFTER_E4, EXPLORER_BODY)
    assert [m.uci for m in result.moves] == ["e7e5", "c7c5"]
    assert result.total == 1800 and result.moves[0].games == 1000
    assert parse_explorer(AFTER_E4, {"moves": [{"uci": "e7e5", "san": "BAD", "white": 1}]}).moves[0].san == "e5"


@pytest.mark.parametrize("data", [None, [], {"moves": None}, {"moves": "x"}, {"moves": [None, 3]}])
def test_a_broken_explorer_answer_is_just_empty(data: Any) -> None:
    assert parse_explorer(AFTER_E4, data).moves == ()


# ---- the explorer, through the store -------------------------------------------------------------------


def test_explorer_asks_once_with_your_token_and_settings(sources: OpeningSources, net: Net) -> None:
    assert OpeningSources.most_played(sources.fetch_explorer(AFTER_E4)).uci == "e7e5"  # type: ignore[union-attr]
    sources.fetch_explorer(AFTER_E4)
    assert len(net.requests) == 1
    request = net.requests[0]
    assert request.url.host == "explorer.lichess.org" and request.url.path == "/lichess"
    assert request.headers["authorization"] == "Bearer lip_FAKE"
    assert request.url.params["ratings"] == "1600,1800,2000"


def test_signed_out_makes_no_request(sources: OpeningSources, net: Net, tokens: Tokens) -> None:
    tokens.value = None
    assert sources.fetch_explorer(AFTER_E4) is None
    assert net.requests == []


def test_offline_is_skipped_cleanly(sources: OpeningSources, net: Net) -> None:
    net.fail = httpx.ConnectError
    assert sources.fetch_explorer(AFTER_E4) is None


@pytest.mark.parametrize("status", [401, 500])
def test_an_error_status_is_skipped_cleanly(sources: OpeningSources, net: Net, status: int) -> None:
    net.status = status
    assert sources.fetch_explorer(AFTER_E4) is None


def test_a_rate_limit_pauses_for_a_minute(sources: OpeningSources, net: Net, clock: Any) -> None:
    net.status = 429
    assert sources.fetch_explorer(AFTER_E4) is None
    assert sources.fetch_explorer(AFTER_E4) is None
    assert len(net.requests) == 1
    clock.advance(seconds=61)
    net.status = 200
    assert sources.fetch_explorer(AFTER_E4) is not None


def test_a_stale_answer_is_refreshed_but_kept_if_that_fails(sources: OpeningSources, net: Net, clock: Any) -> None:
    sources.fetch_explorer(AFTER_E4)
    clock.advance(days=31)
    net.fail = httpx.ConnectError
    assert sources.fetch_explorer(AFTER_E4) is not None
    net.fail = None
    sources.fetch_explorer(AFTER_E4)
    assert len(net.requests) == 3


def test_reading_the_store_never_uses_the_network(sources: OpeningSources, net: Net) -> None:
    assert sources.stored_explorer(AFTER_E4) is None
    assert net.requests == []


def test_changing_the_settings_is_a_different_answer(sources: OpeningSources, net: Net) -> None:
    sources.fetch_explorer(AFTER_E4)
    sources.set_explorer_settings("masters", [2500])
    sources.fetch_explorer(AFTER_E4)
    assert len(net.requests) == 2 and net.requests[1].url.path == "/masters"
    assert "ratings" not in net.requests[1].url.params


@pytest.mark.parametrize(
    ("source", "ratings"), [("x", [1600]), ("lichess", []), ("lichess", [1601]), ("lichess", "1600")]
)
def test_bad_explorer_settings_are_refused(sources: OpeningSources, source: Any, ratings: Any) -> None:
    with pytest.raises(ValidationError):
        sources.set_explorer_settings(source, ratings)


# ---- Wikibooks, through the store ------------------------------------------------------------------------


def test_a_page_is_fetched_once_and_needs_no_sign_in(sources: OpeningSources, net: Net, tokens: Tokens) -> None:
    tokens.value = None
    page = sources.fetch_page(TITLE)
    assert page is not None and page.status == "ok" and page.revision_id == 42
    sources.fetch_page(TITLE)
    assert len(net.requests) == 1
    request = net.requests[0]
    assert request.url.host == "en.wikibooks.org" and "authorization" not in request.headers
    assert request.url.params["titles"] == TITLE


def test_a_missing_page_is_remembered(sources: OpeningSources, net: Net) -> None:
    net.wiki = {"query": {"pages": [{"title": "x", "missing": True}]}}
    assert sources.fetch_page(TITLE).status == "missing"  # type: ignore[union-attr]
    assert sources.fetch_page(TITLE).status == "missing"  # type: ignore[union-attr]
    assert len(net.requests) == 1


def test_offline_with_nothing_stored_is_no_page(sources: OpeningSources, net: Net) -> None:
    net.fail = httpx.ConnectError
    assert sources.fetch_page(TITLE) is None


def test_the_setting_turns_all_use_off(sources: OpeningSources, net: Net) -> None:
    sources.set_use_wikibooks(False)
    assert sources.fetch_page(TITLE) is None
    assert net.requests == []


def test_a_good_page_isnt_replaced_when_it_later_goes_missing(sources: OpeningSources, net: Net, clock: Any) -> None:
    sources.fetch_page(TITLE)
    clock.advance(days=31)
    net.wiki = {"query": {"pages": [{"title": "x", "missing": True}]}}
    sources.fetch_page(TITLE)
    assert sources.stored_page(TITLE).status == "ok"  # type: ignore[union-attr]


def test_a_link_is_only_ever_built_from_the_title(sources: OpeningSources) -> None:
    page = sources.fetch_page(TITLE)
    assert page is not None and "example.org" not in page.text
    assert "example.org" not in page_url(page.title)


# ---- the run-level cap (FR-12.7b) ------------------------------------------------------------------------


def _configure(services: Any, cap: float) -> None:
    services.llm_settings.set_key("anthropic", "sk-ant-FAKE0000000000000000")
    services.llm_settings.update("anthropic", "claude-haiku-5-5", "low", cap, 5.0)


def test_a_run_is_blocked_though_each_request_passes(services: Any) -> None:
    _configure(services, 0.01)
    usage = services.llm_usage
    one = usage.quote("opening_line", 2000)
    assert one.state == "ok", one.message
    run = usage.quote_batch("openings", [("opening_line", 2000)] * 40)
    assert run.state == "over_cap"
    assert run.worst_usd == pytest.approx(one.estimate.worst_usd * 40)
    assert len(run.per_request_worst) == 40


def test_the_batch_cost_follows_the_price_table(services: Any) -> None:
    _configure(services, 5.0)
    before = services.llm_usage.quote_batch("openings", [("opening_line", 2000)]).typical_usd
    cfg = services.llm_settings.config("openings")
    services.llm_settings.save_price(cfg.provider, cfg.model, 100.0, 500.0)
    after = services.llm_usage.quote_batch("openings", [("opening_line", 2000)]).typical_usd
    assert after > before * 10


def test_a_request_counts_what_the_run_has_spent(services: Any) -> None:
    _configure(services, 0.01)
    usage = services.llm_usage
    assert usage.quote("opening_line", 2000).state == "ok"
    assert usage.quote("opening_line", 2000, run_spent=0.0099).state == "over_cap"


def test_no_model_is_reported_for_a_batch(services: Any) -> None:
    assert services.llm_usage.quote_batch("openings", [("opening_line", 100)]).state in ("not_configured", "no_model")
