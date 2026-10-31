"""Look up a home's living area in BBR from the address already on the account."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re

import requests

_LOGGER = logging.getLogger(__name__)

ADDRESS_SEARCH_URL = "https://adressevaelger.dk/adresser/soeg"
ADDRESS_SEARCH_TOKEN = "adressevaelger123"
BBR_URL = "https://graphql.datafordeler.dk/BBR/v3"
_ADDRESS_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def address_search_text(street, city) -> str:
    """Join the street and town already stored for the customer."""
    parts = []
    for value in (street, city):
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return ", ".join(parts)


def address_id_from_search(payload) -> str | None:
    """Return the id only when the search finds exactly one address."""
    if not isinstance(payload, dict):
        return None
    hits = payload.get("fund")
    if not isinstance(hits, list):
        return None
    matches = []
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("type") != "adresse":
            continue
        address_id = hit.get("id")
        if isinstance(address_id, str) and _ADDRESS_ID.match(address_id):
            matches.append(address_id)
    if len(matches) != 1:
        return None
    return matches[0]


def bbr_area_query(address_id, as_of) -> str | None:
    """GraphQL for the dwelling registered on one address."""
    if not isinstance(address_id, str) or not _ADDRESS_ID.match(address_id):
        return None
    if not isinstance(as_of, str) or not re.fullmatch(r"[0-9TZ:.-]+", as_of):
        return None
    return (
        "query { BBR_Enhed("
        f'where: {{ adresseIdentificerer: {{ eq: "{address_id}" }} }} '
        f'virkningstid: "{as_of}" registreringstid: "{as_of}" first: 5'
        ") { nodes { enh027ArealTilBeboelse enh026EnhedensSamledeAreal } } }"
    )


def _positive_area(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw <= 0:
        return None
    return float(raw)


def living_area_from_bbr(payload):
    """Square metres of living area. Falls back to the unit's total area."""
    if not isinstance(payload, dict):
        return None
    enhed = (payload.get("data") or {}).get("BBR_Enhed") if isinstance(payload.get("data"), dict) else None
    nodes = enhed.get("nodes") if isinstance(enhed, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return None
    areas = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        area = _positive_area(node.get("enh027ArealTilBeboelse"))
        if area is None:
            area = _positive_area(node.get("enh026EnhedensSamledeAreal"))
        if area is not None:
            areas.append(area)
    if not areas:
        return None
    return float(sum(areas))


def lookup_floor_area(street, city, api_key):
    """Living area in m² for the customer's address. None when BBR cannot answer."""
    text = address_search_text(street, city)
    if not text or not isinstance(api_key, str) or not api_key.strip():
        return None
    try:
        search = requests.get(
            ADDRESS_SEARCH_URL,
            params={"tekst": text, "token": ADDRESS_SEARCH_TOKEN},
            timeout=30,
        )
        search.raise_for_status()
        address_id = address_id_from_search(search.json())
        if address_id is None:
            _LOGGER.warning("No single address match for %s", text)
            return None
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = bbr_area_query(address_id, as_of)
        if query is None:
            return None
        bbr = requests.post(
            BBR_URL,
            params={"apiKey": api_key.strip()},
            json={"query": query},
            timeout=30,
        )
        bbr.raise_for_status()
        body = bbr.json()
    except (requests.exceptions.RequestException, ValueError) as error:
        _LOGGER.warning("BBR lookup failed: %s", error)
        return None
    if isinstance(body, dict) and body.get("errors"):
        _LOGGER.warning("BBR rejected the area query: %s", body.get("errors"))
        return None
    return living_area_from_bbr(body)
