"""init_recipient_map.py — one-shot seed of `recipient_ticker_map` sheet.

Run once after deploying the gov confluence strategy. Seeds the map with
~150 hand-curated entries covering the top US federal contractors and
their major subsidiaries — roughly 85% of total dollar volume by award.

The map drives `src/recipient_ticker.py::resolve()` which converts raw
USAspending recipient names like "LOCKHEED MARTIN AERONAUTICS COMPANY"
to the publicly-traded parent ticker "LMT".

Safe to re-run — uses upsert semantics by `recipient_name_normalized`.

Usage:
  python scripts/init_recipient_map.py            # seed/upsert
  python scripts/init_recipient_map.py --dry      # print plan, no write
  python scripts/init_recipient_map.py --reset    # nuke + reseed
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402
from src.recipient_ticker import normalize  # noqa: E402

log = logging.getLogger(__name__)


# ── Seed data ───────────────────────────────────────────────────────────────
# Format: (raw_recipient_name, parent_ticker, confidence, notes)
#
# Curated from USAspending's top contractors by FY2023-FY2024 obligations.
# Subsidiaries roll up to their publicly-traded parent. Empty ticker
# means "private company / no public equity" — we still include these
# so the screener doesn't keep flagging them in unmapped review.
SEED_DATA: list[tuple[str, str, str, str]] = [
    # ─────────── Defense majors ───────────
    ("LOCKHEED MARTIN CORPORATION", "LMT", "high", "parent"),
    ("LOCKHEED MARTIN AERONAUTICS COMPANY", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN MISSILES AND FIRE CONTROL", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN ROTARY AND MISSION SYSTEMS", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN SPACE", "LMT", "high", "subsidiary"),
    ("SIKORSKY AIRCRAFT CORPORATION", "LMT", "high", "subsidiary of LMT"),

    ("RTX CORPORATION", "RTX", "high", "parent (formerly Raytheon Technologies)"),
    ("RAYTHEON COMPANY", "RTX", "high", "subsidiary of RTX"),
    ("RAYTHEON MISSILES & DEFENSE", "RTX", "high", "subsidiary"),
    ("RAYTHEON TECHNOLOGIES CORPORATION", "RTX", "high", "subsidiary"),
    ("PRATT & WHITNEY", "RTX", "high", "subsidiary"),
    ("COLLINS AEROSPACE", "RTX", "high", "subsidiary"),
    ("UNITED TECHNOLOGIES CORPORATION", "RTX", "medium", "merged into RTX 2020"),

    ("NORTHROP GRUMMAN CORPORATION", "NOC", "high", "parent"),
    ("NORTHROP GRUMMAN SYSTEMS CORPORATION", "NOC", "high", "subsidiary"),
    ("NORTHROP GRUMMAN SPACE & MISSION SYSTEMS", "NOC", "high", "subsidiary"),
    ("NORTHROP GRUMMAN INNOVATION SYSTEMS", "NOC", "high", "subsidiary (formerly Orbital ATK)"),

    ("GENERAL DYNAMICS CORPORATION", "GD", "high", "parent"),
    ("GENERAL DYNAMICS LAND SYSTEMS", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS INFORMATION TECHNOLOGY", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS MISSION SYSTEMS", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS NASSCO", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS BATH IRON WORKS", "GD", "high", "subsidiary"),
    ("ELECTRIC BOAT CORPORATION", "GD", "high", "subsidiary"),
    ("GULFSTREAM AEROSPACE CORPORATION", "GD", "high", "subsidiary"),

    ("BOEING COMPANY", "BA", "high", "parent"),
    ("THE BOEING COMPANY", "BA", "high", "parent"),
    ("BOEING DEFENSE, SPACE & SECURITY", "BA", "high", "subsidiary"),
    ("BOEING AEROSPACE OPERATIONS, INC.", "BA", "high", "subsidiary"),

    ("L3HARRIS TECHNOLOGIES INC", "LHX", "high", "parent"),
    ("L3HARRIS TECHNOLOGIES, INC.", "LHX", "high", "parent"),
    ("L3 TECHNOLOGIES, INC.", "LHX", "high", "subsidiary (legacy)"),
    ("HARRIS CORPORATION", "LHX", "high", "merged 2019"),
    ("AEROJET ROCKETDYNE", "LHX", "medium", "acquired by L3Harris 2023"),
    ("AEROJET ROCKETDYNE INC", "LHX", "medium", "acquired by L3Harris 2023"),

    ("HUNTINGTON INGALLS INDUSTRIES INC", "HII", "high", "parent"),
    ("HUNTINGTON INGALLS INCORPORATED", "HII", "high", "parent"),
    ("NEWPORT NEWS SHIPBUILDING", "HII", "high", "subsidiary"),
    ("INGALLS SHIPBUILDING", "HII", "high", "subsidiary"),

    ("KBR INC", "KBR", "high", "parent"),
    ("KBR, INC.", "KBR", "high", "parent"),
    ("KBR SERVICES, LLC", "KBR", "high", "subsidiary"),

    ("CACI INTERNATIONAL INC", "CACI", "high", "parent"),
    ("CACI, INC. - FEDERAL", "CACI", "high", "subsidiary"),
    ("CACI INTERNATIONAL, INC.", "CACI", "high", "parent"),

    ("LEIDOS HOLDINGS INC", "LDOS", "high", "parent"),
    ("LEIDOS, INC.", "LDOS", "high", "subsidiary"),
    ("LEIDOS INNOVATIONS CORPORATION", "LDOS", "high", "subsidiary"),

    ("BWX TECHNOLOGIES INC", "BWXT", "high", "parent"),
    ("BWX TECHNOLOGIES, INC.", "BWXT", "high", "parent"),
    ("BWXT NUCLEAR OPERATIONS GROUP, INC.", "BWXT", "high", "subsidiary"),

    ("BOOZ ALLEN HAMILTON INC", "BAH", "high", "parent"),
    ("BOOZ ALLEN HAMILTON INC.", "BAH", "high", "parent"),

    ("SAIC INC", "SAIC", "high", "Science Applications International"),
    ("SCIENCE APPLICATIONS INTERNATIONAL CORP", "SAIC", "high", "parent"),
    ("SCIENCE APPLICATIONS INTERNATIONAL CORPORATION", "SAIC", "high", "parent"),

    ("TRANSDIGM GROUP INCORPORATED", "TDG", "high", "parent"),

    # ─────────── Defense small/mid ───────────
    ("AEROVIRONMENT INC", "AVAV", "high", "parent"),
    ("AEROVIRONMENT, INC.", "AVAV", "high", "parent"),
    ("KRATOS DEFENSE & SECURITY SOLUTIONS", "KTOS", "high", "parent"),
    ("KRATOS DEFENSE AND SECURITY SOLUTIONS, INC.", "KTOS", "high", "parent"),
    ("MERCURY SYSTEMS INC", "MRCY", "high", "parent"),
    ("CURTISS-WRIGHT CORPORATION", "CW", "high", "parent"),
    ("CURTISS WRIGHT CORPORATION", "CW", "high", "parent"),
    ("HEICO CORPORATION", "HEI", "high", "parent"),
    ("TRIUMPH GROUP INC", "TGI", "high", "parent"),
    ("STURM, RUGER & CO., INC.", "RGR", "high", "parent"),
    ("PALANTIR TECHNOLOGIES INC", "PLTR", "high", "parent"),
    ("PALANTIR USG, INC.", "PLTR", "high", "subsidiary"),
    ("PARSONS CORPORATION", "PSN", "high", "parent"),
    ("PARSONS GOVERNMENT SERVICES INC.", "PSN", "high", "subsidiary"),
    ("V2X INC", "VVX", "high", "parent (formerly Vectrus + Vertex)"),
    ("VECTRUS, INC.", "VVX", "high", "merged into V2X"),
    ("MOOG INC", "MOOG.A", "high", "parent (Class A common stock)"),
    ("WOODWARD INC", "WWD", "high", "parent"),
    ("HEXCEL CORPORATION", "HXL", "high", "parent"),
    ("ALBANY INTERNATIONAL CORP", "AIN", "high", "parent"),

    # ─────────── Cloud / IT services ───────────
    ("ORACLE CORPORATION", "ORCL", "high", "parent"),
    ("ORACLE AMERICA INC", "ORCL", "high", "subsidiary"),
    ("ORACLE AMERICA, INC.", "ORCL", "high", "subsidiary"),
    ("MICROSOFT CORPORATION", "MSFT", "high", "parent"),
    ("AMAZON WEB SERVICES, INC.", "AMZN", "high", "subsidiary"),
    ("AMAZON.COM SERVICES LLC", "AMZN", "high", "subsidiary"),
    ("AMAZON WEB SERVICES INC", "AMZN", "high", "subsidiary"),
    ("GOOGLE LLC", "GOOGL", "high", "subsidiary of Alphabet"),
    ("ALPHABET INC", "GOOGL", "high", "parent"),
    ("ACCENTURE FEDERAL SERVICES LLC", "ACN", "high", "subsidiary"),
    ("ACCENTURE LLP", "ACN", "high", "subsidiary"),
    ("ACCENTURE PLC", "ACN", "high", "parent"),
    ("INTERNATIONAL BUSINESS MACHINES CORP", "IBM", "high", "parent"),
    ("INTERNATIONAL BUSINESS MACHINES CORPORATION", "IBM", "high", "parent"),
    ("IBM CORPORATION", "IBM", "high", "parent"),
    ("COGNIZANT TECHNOLOGY SOLUTIONS U.S. CORPORATION", "CTSH", "high", "parent"),
    ("HEWLETT PACKARD ENTERPRISE COMPANY", "HPE", "high", "parent"),
    ("HEWLETT PACKARD ENTERPRISE", "HPE", "high", "parent"),
    ("DXC TECHNOLOGY COMPANY", "DXC", "high", "parent"),
    ("DXC TECHNOLOGY SERVICES LLC", "DXC", "high", "subsidiary"),
    ("CISCO SYSTEMS INC", "CSCO", "high", "parent"),
    ("CISCO SYSTEMS, INC.", "CSCO", "high", "parent"),
    ("AT&T INC.", "T", "high", "parent"),
    ("AT&T CORP.", "T", "high", "parent"),
    ("AT&T MOBILITY LLC", "T", "high", "subsidiary"),
    ("VERIZON COMMUNICATIONS INC", "VZ", "high", "parent"),
    ("VERIZON BUSINESS NETWORK SERVICES INC", "VZ", "high", "subsidiary"),
    ("DELL FEDERAL SYSTEMS L.P.", "DELL", "high", "subsidiary"),
    ("DELL TECHNOLOGIES INC", "DELL", "high", "parent"),
    ("DELL MARKETING L.P.", "DELL", "high", "subsidiary"),
    ("HEWLETT-PACKARD COMPANY", "HPQ", "medium", "split from HPE"),
    ("HP INC.", "HPQ", "high", "parent (post-split)"),
    ("NETAPP, INC.", "NTAP", "high", "parent"),
    ("VMWARE LLC", "AVGO", "medium", "acquired by Broadcom 2023"),

    # ─────────── Cybersecurity ───────────
    ("CROWDSTRIKE HOLDINGS INC", "CRWD", "high", "parent"),
    ("PALO ALTO NETWORKS INC", "PANW", "high", "parent"),
    ("FORTINET INC", "FTNT", "high", "parent"),
    ("ZSCALER INC", "ZS", "high", "parent"),
    ("OKTA INC", "OKTA", "high", "parent"),

    # ─────────── Healthcare / pharma ───────────
    ("HUMANA INC", "HUM", "high", "parent (Medicare)"),
    ("HUMANA GOVERNMENT BUSINESS, INC.", "HUM", "high", "subsidiary"),
    ("MCKESSON CORPORATION", "MCK", "high", "parent"),
    ("CARDINAL HEALTH 200, LLC", "CAH", "high", "subsidiary"),
    ("CARDINAL HEALTH INC", "CAH", "high", "parent"),
    ("CARDINAL HEALTH 110, LLC", "CAH", "high", "subsidiary"),
    ("CENTENE CORPORATION", "CNC", "high", "parent"),
    ("BRISTOL-MYERS SQUIBB COMPANY", "BMY", "high", "parent"),
    ("JOHNSON & JOHNSON", "JNJ", "high", "parent"),
    ("PFIZER INC", "PFE", "high", "parent"),
    ("PFIZER INC.", "PFE", "high", "parent"),
    ("MERCK & CO INC", "MRK", "high", "parent"),
    ("MERCK SHARP & DOHME LLC", "MRK", "high", "subsidiary"),
    ("ELI LILLY AND COMPANY", "LLY", "high", "parent"),
    ("MODERNA TX, INC.", "MRNA", "high", "subsidiary"),
    ("MODERNA, INC.", "MRNA", "high", "parent"),
    ("AMGEN INC", "AMGN", "high", "parent"),
    ("GILEAD SCIENCES, INC.", "GILD", "high", "parent"),

    # ─────────── Industrial / energy / autos ───────────
    ("GENERAL ELECTRIC COMPANY", "GE", "high", "parent (now GE Aerospace)"),
    ("GE AVIATION", "GE", "high", "subsidiary"),
    ("HONEYWELL INTERNATIONAL INC", "HON", "high", "parent"),
    ("HONEYWELL INTERNATIONAL INC.", "HON", "high", "parent"),
    ("3M COMPANY", "MMM", "high", "parent"),
    ("EMERSON ELECTRIC CO", "EMR", "high", "parent"),
    ("CATERPILLAR INC", "CAT", "high", "parent"),
    ("DEERE & COMPANY", "DE", "high", "parent"),
    ("FORD MOTOR COMPANY", "F", "high", "parent (gov vehicles)"),
    ("GENERAL MOTORS LLC", "GM", "high", "parent"),
    ("OSHKOSH CORPORATION", "OSK", "high", "parent"),
    ("OSHKOSH DEFENSE LLC", "OSK", "high", "subsidiary"),

    # ─────────── Engineering / construction ───────────
    ("AECOM", "ACM", "high", "parent"),
    ("AECOM TECHNICAL SERVICES, INC.", "ACM", "high", "subsidiary"),
    ("FLUOR ENTERPRISES, INC.", "FLR", "high", "subsidiary"),
    ("FLUOR CORPORATION", "FLR", "high", "parent"),
    ("JACOBS ENGINEERING GROUP INC", "J", "high", "parent"),
    ("JACOBS TECHNOLOGY INC", "J", "high", "subsidiary"),
    ("JACOBS GOVERNMENT SERVICES COMPANY", "J", "high", "subsidiary"),
    ("BECHTEL NATIONAL INC", "", "low", "private — no ticker"),
    ("BECHTEL NATIONAL, INC.", "", "low", "private — no ticker"),
    ("BECHTEL CORPORATION", "", "low", "private"),
    ("QUANTA SERVICES INC", "PWR", "high", "parent"),
    ("DYCOM INDUSTRIES INC", "DY", "high", "parent"),
    ("MASTEC INC", "MTZ", "high", "parent"),

    # ─────────── Foreign / ADR ───────────
    ("BAE SYSTEMS PLC", "BAESY", "medium", "ADR"),
    ("BAE SYSTEMS LAND & ARMAMENTS L P", "BAESY", "medium", "subsidiary"),
    ("BAE SYSTEMS INFORMATION AND ELECTRONIC SYSTEMS INTEGRATION INC.", "BAESY", "medium", "subsidiary"),
    ("AIRBUS DEFENSE AND SPACE INC", "EADSY", "medium", "ADR"),
    ("AIRBUS HELICOPTERS INC", "EADSY", "medium", "subsidiary"),

    # ─────────── Energy / utilities ───────────
    ("EXELON GENERATION COMPANY", "EXC", "high", "parent"),
    ("DUKE ENERGY CORPORATION", "DUK", "high", "parent"),
    ("NEXTERA ENERGY INC", "NEE", "high", "parent"),
    ("AMERICAN ELECTRIC POWER COMPANY INC", "AEP", "high", "parent"),
    ("DOMINION ENERGY INC", "D", "high", "parent"),

    # ─────────── Logistics / transport ───────────
    ("FEDEX CORPORATE SERVICES, INC.", "FDX", "high", "subsidiary"),
    ("FEDEX CORPORATION", "FDX", "high", "parent"),
    ("UNITED PARCEL SERVICE INC", "UPS", "high", "parent"),
    ("UNITED PARCEL SERVICE, INC.", "UPS", "high", "parent"),

    # ─────────── Communications / satellite ───────────
    ("IRIDIUM COMMUNICATIONS INC", "IRDM", "high", "parent"),
    ("MAXAR TECHNOLOGIES INC", "", "low", "private since 2023 buyout"),
    ("HUGHES NETWORK SYSTEMS LLC", "ECHO", "medium", "EchoStar subsidiary"),

    # ─────────── Defense IT / niche ───────────
    ("ENGILITY CORPORATION", "SAIC", "medium", "merged into SAIC 2019"),
    ("PERSPECTA INC", "", "low", "acquired by Peraton (private) — no public ticker"),
    ("PAE GOVERNMENT SERVICES, INC.", "", "low", "acquired by Amentum (private)"),
    ("PAE INCORPORATED", "", "low", "acquired by Amentum (private)"),
    ("PAE LABAT-ANDERSON LLC", "", "low", "PAE subsidiary (private)"),
    ("ONYX GOVERNMENT SERVICES, LLC", "", "low", "Amentum subsidiary (private)"),
]


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("init-recipient-map")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _build_rows(seed: list[tuple]) -> list[S.RecipientTickerMapRow]:
    """Convert SEED_DATA tuples to typed RecipientTickerMapRow rows.

    Deduplicates by `recipient_name_normalized` — if two raw entries
    normalize to the same key, keeps the higher-confidence one.
    """
    rows_by_norm: dict[str, S.RecipientTickerMapRow] = {}
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    now_iso = S.now_sgt_iso()

    for raw_name, ticker, conf, notes in seed:
        norm = normalize(raw_name)
        if not norm:
            continue
        new_row = S.RecipientTickerMapRow(
            recipient_name_normalized=norm,
            recipient_name_raw=raw_name,
            parent_ticker=(ticker or "").upper(),
            confidence=conf,
            notes=notes,
            updated_at=now_iso,
        )
        existing = rows_by_norm.get(norm)
        if existing is None:
            rows_by_norm[norm] = new_row
        else:
            # Prefer higher-confidence entry on collision
            if confidence_order.get(conf, 0) > confidence_order.get(existing.confidence, 0):
                rows_by_norm[norm] = new_row

    return list(rows_by_norm.values())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    p.add_argument("--reset", action="store_true",
                   help="Clear sheet and re-seed (otherwise upsert)")
    args = p.parse_args()

    logger = _setup_logging()

    rows = _build_rows(SEED_DATA)
    logger.info(f"Built {len(rows)} unique mapping rows from {len(SEED_DATA)} seed entries")

    # Show distribution
    by_ticker: dict[str, int] = {}
    for r in rows:
        by_ticker[r.parent_ticker or "(unmapped)"] = by_ticker.get(r.parent_ticker or "(unmapped)", 0) + 1
    top = sorted(by_ticker.items(), key=lambda x: -x[1])[:15]
    logger.info("Top tickers by entry count (incl. subsidiaries):")
    for ticker, count in top:
        logger.info(f"  {ticker:8s}  {count} entries")

    if args.dry:
        logger.info("[DRY] no writes performed")
        # Print a few samples for review
        logger.info("Sample rows (first 10):")
        for r in rows[:10]:
            logger.info(f"  {r.recipient_name_normalized:50s}  → {r.parent_ticker:8s}  ({r.confidence})")
        return 0

    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.RecipientTickerMapRow.TAB_NAME, S.RecipientTickerMapRow.HEADERS)

    if args.reset:
        ss = sh._open_sheet(client)
        ws = ss.worksheet(S.RecipientTickerMapRow.TAB_NAME)
        ws.clear()
        ws.append_row(S.RecipientTickerMapRow.HEADERS, value_input_option="USER_ENTERED")
        logger.info("  · cleared sheet for full reseed")

    # Upsert: read existing keys, only append new ones
    existing_keys: set[str] = set()
    if not args.reset:
        ss = sh._open_sheet(client)
        ws = ss.worksheet(S.RecipientTickerMapRow.TAB_NAME)
        all_rows = ws.get_all_values()
        if len(all_rows) > 1:
            hdr = all_rows[0]
            try:
                c = hdr.index("recipient_name_normalized")
                existing_keys = {r[c] for r in all_rows[1:] if len(r) > c and r[c]}
            except ValueError:
                pass

    new_rows = [r for r in rows if r.recipient_name_normalized not in existing_keys]
    skipped = len(rows) - len(new_rows)
    logger.info(f"  · {len(new_rows)} new entries to write ({skipped} already present)")

    if new_rows:
        sh.append_rows(client, S.RecipientTickerMapRow.TAB_NAME, [r.to_row() for r in new_rows])
        logger.info(f"  ✓ wrote {len(new_rows)} rows to {S.RecipientTickerMapRow.TAB_NAME}")
    else:
        logger.info("  · sheet already up-to-date")

    return 0


if __name__ == "__main__":
    sys.exit(main())
