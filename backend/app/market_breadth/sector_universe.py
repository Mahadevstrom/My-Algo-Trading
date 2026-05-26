from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectorDefinition:
    name: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class NiftyConstituent:
    company_name: str
    industry: str
    symbol: str
    aliases: tuple[str, ...] = ()


NIFTY_50_CONSTITUENTS: tuple[NiftyConstituent, ...] = (
    NiftyConstituent("Adani Enterprises Ltd.", "Metals & Mining", "ADANIENT"),
    NiftyConstituent("Adani Ports and Special Economic Zone Ltd.", "Services", "ADANIPORTS"),
    NiftyConstituent("Apollo Hospitals Enterprise Ltd.", "Healthcare", "APOLLOHOSP"),
    NiftyConstituent("Asian Paints Ltd.", "Consumer Durables", "ASIANPAINT"),
    NiftyConstituent("Axis Bank Ltd.", "Financial Services", "AXISBANK"),
    NiftyConstituent("Bajaj Auto Ltd.", "Automobile and Auto Components", "BAJAJ-AUTO"),
    NiftyConstituent("Bajaj Finance Ltd.", "Financial Services", "BAJFINANCE"),
    NiftyConstituent("Bajaj Finserv Ltd.", "Financial Services", "BAJAJFINSV"),
    NiftyConstituent("Bharat Electronics Ltd.", "Capital Goods", "BEL"),
    NiftyConstituent("Bharti Airtel Ltd.", "Telecommunication", "BHARTIARTL"),
    NiftyConstituent("Cipla Ltd.", "Healthcare", "CIPLA"),
    NiftyConstituent("Coal India Ltd.", "Oil Gas & Consumable Fuels", "COALINDIA"),
    NiftyConstituent("Dr. Reddy's Laboratories Ltd.", "Healthcare", "DRREDDY"),
    NiftyConstituent("Eicher Motors Ltd.", "Automobile and Auto Components", "EICHERMOT"),
    NiftyConstituent("Eternal Ltd.", "Consumer Services", "ETERNAL", ("ZOMATO",)),
    NiftyConstituent("Grasim Industries Ltd.", "Construction Materials", "GRASIM"),
    NiftyConstituent("HCL Technologies Ltd.", "Information Technology", "HCLTECH"),
    NiftyConstituent("HDFC Bank Ltd.", "Financial Services", "HDFCBANK"),
    NiftyConstituent("HDFC Life Insurance Company Ltd.", "Financial Services", "HDFCLIFE"),
    NiftyConstituent("Hindalco Industries Ltd.", "Metals & Mining", "HINDALCO"),
    NiftyConstituent("Hindustan Unilever Ltd.", "Fast Moving Consumer Goods", "HINDUNILVR"),
    NiftyConstituent("ICICI Bank Ltd.", "Financial Services", "ICICIBANK"),
    NiftyConstituent("ITC Ltd.", "Fast Moving Consumer Goods", "ITC"),
    NiftyConstituent("Infosys Ltd.", "Information Technology", "INFY"),
    NiftyConstituent("InterGlobe Aviation Ltd.", "Services", "INDIGO"),
    NiftyConstituent("JSW Steel Ltd.", "Metals & Mining", "JSWSTEEL"),
    NiftyConstituent("Jio Financial Services Ltd.", "Financial Services", "JIOFIN"),
    NiftyConstituent("Kotak Mahindra Bank Ltd.", "Financial Services", "KOTAKBANK"),
    NiftyConstituent("Larsen & Toubro Ltd.", "Construction", "LT"),
    NiftyConstituent("Mahindra & Mahindra Ltd.", "Automobile and Auto Components", "M&M"),
    NiftyConstituent("Maruti Suzuki India Ltd.", "Automobile and Auto Components", "MARUTI"),
    NiftyConstituent("Max Healthcare Institute Ltd.", "Healthcare", "MAXHEALTH"),
    NiftyConstituent("NTPC Ltd.", "Power", "NTPC"),
    NiftyConstituent("Nestle India Ltd.", "Fast Moving Consumer Goods", "NESTLEIND"),
    NiftyConstituent("Oil & Natural Gas Corporation Ltd.", "Oil Gas & Consumable Fuels", "ONGC"),
    NiftyConstituent("Power Grid Corporation of India Ltd.", "Power", "POWERGRID"),
    NiftyConstituent("Reliance Industries Ltd.", "Oil Gas & Consumable Fuels", "RELIANCE"),
    NiftyConstituent("SBI Life Insurance Company Ltd.", "Financial Services", "SBILIFE"),
    NiftyConstituent("Shriram Finance Ltd.", "Financial Services", "SHRIRAMFIN"),
    NiftyConstituent("State Bank of India", "Financial Services", "SBIN"),
    NiftyConstituent("Sun Pharmaceutical Industries Ltd.", "Healthcare", "SUNPHARMA"),
    NiftyConstituent("Tata Consultancy Services Ltd.", "Information Technology", "TCS"),
    NiftyConstituent("Tata Consumer Products Ltd.", "Fast Moving Consumer Goods", "TATACONSUM"),
    NiftyConstituent("Tata Motors Passenger Vehicles Ltd.", "Automobile and Auto Components", "TMPV", ("TATAMOTORS",)),
    NiftyConstituent("Tata Steel Ltd.", "Metals & Mining", "TATASTEEL"),
    NiftyConstituent("Tech Mahindra Ltd.", "Information Technology", "TECHM"),
    NiftyConstituent("Titan Company Ltd.", "Consumer Durables", "TITAN"),
    NiftyConstituent("Trent Ltd.", "Consumer Services", "TRENT"),
    NiftyConstituent("UltraTech Cement Ltd.", "Construction Materials", "ULTRACEMCO"),
    NiftyConstituent("Wipro Ltd.", "Information Technology", "WIPRO"),
)


NIFTY_BANK_CONSTITUENTS: tuple[NiftyConstituent, ...] = (
    NiftyConstituent("AU Small Finance Bank Ltd.", "Financial Services", "AUBANK"),
    NiftyConstituent("Axis Bank Ltd.", "Financial Services", "AXISBANK"),
    NiftyConstituent("Bank of Baroda", "Financial Services", "BANKBARODA"),
    NiftyConstituent("Canara Bank", "Financial Services", "CANBK"),
    NiftyConstituent("Federal Bank Ltd.", "Financial Services", "FEDERALBNK"),
    NiftyConstituent("HDFC Bank Ltd.", "Financial Services", "HDFCBANK"),
    NiftyConstituent("ICICI Bank Ltd.", "Financial Services", "ICICIBANK"),
    NiftyConstituent("IDFC First Bank Ltd.", "Financial Services", "IDFCFIRSTB"),
    NiftyConstituent("IndusInd Bank Ltd.", "Financial Services", "INDUSINDBK"),
    NiftyConstituent("Kotak Mahindra Bank Ltd.", "Financial Services", "KOTAKBANK"),
    NiftyConstituent("Punjab National Bank", "Financial Services", "PNB"),
    NiftyConstituent("State Bank of India", "Financial Services", "SBIN"),
    NiftyConstituent("Union Bank of India", "Financial Services", "UNIONBANK"),
    NiftyConstituent("Yes Bank Ltd.", "Financial Services", "YESBANK"),
)


INDEX_CONSTITUENTS: dict[str, tuple[NiftyConstituent, ...]] = {
    "NIFTY": NIFTY_50_CONSTITUENTS,
    "BANKNIFTY": NIFTY_BANK_CONSTITUENTS,
}

INDEX_DISPLAY_NAMES: dict[str, str] = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}

INDEX_ALIASES: dict[str, str] = {
    "NIFTY": "NIFTY",
    "NIFTY50": "NIFTY",
    "NIFTY_50": "NIFTY",
    "NIFTY 50": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTY_BANK": "BANKNIFTY",
    "NIFTY BANK": "BANKNIFTY",
}


SECTOR_UNIVERSE: dict[str, SectorDefinition] = {
    "BANKING": SectorDefinition(
        "BANKING",
        ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"),
    ),
    "FINANCIAL_SERVICES": SectorDefinition(
        "FINANCIAL_SERVICES",
        ("BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN", "ICICIGI", "CHOLAFIN"),
    ),
    "IT": SectorDefinition("IT", ("TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "MPHASIS")),
    "AUTO": SectorDefinition("AUTO", ("MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR")),
    "FMCG": SectorDefinition("FMCG", ("ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "GODREJCP")),
    "PHARMA": SectorDefinition("PHARMA", ("SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "LUPIN")),
    "METAL": SectorDefinition("METAL", ("TATASTEEL", "JSWSTEEL", "HINDALCO", "COALINDIA", "VEDL", "NMDC")),
    "ENERGY": SectorDefinition("ENERGY", ("RELIANCE", "NTPC", "POWERGRID", "ADANIGREEN", "ADANIPOWER", "TATAPOWER")),
    "REALTY": SectorDefinition("REALTY", ("DLF", "LODHA", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD")),
    "PSU_BANK": SectorDefinition("PSU_BANK", ("SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "IOB")),
    "CONSUMER_DURABLES": SectorDefinition(
        "CONSUMER_DURABLES",
        ("TITAN", "VOLTAS", "DIXON", "BLUESTARCO", "CROMPTON", "HAVELLS"),
    ),
    "OIL_GAS": SectorDefinition("OIL_GAS", ("RELIANCE", "ONGC", "IOC", "BPCL", "HINDPETRO", "GAIL", "OIL")),
    "CEMENT": SectorDefinition("CEMENT", ("ULTRACEMCO", "GRASIM", "AMBUJACEM", "ACC", "SHREECEM")),
    "TELECOM": SectorDefinition("TELECOM", ("BHARTIARTL", "INDUSTOWER", "IDEA", "TATACOMM")),
}


NIFTY_HEAVYWEIGHTS: tuple[str, ...] = (
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "LT",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "AXISBANK",
    "KOTAKBANK",
    "HINDUNILVR",
    "BAJFINANCE",
    "MARUTI",
    "M&M",
)


def all_symbols() -> list[str]:
    symbols: set[str] = set(NIFTY_HEAVYWEIGHTS)
    for definition in SECTOR_UNIVERSE.values():
        symbols.update(definition.symbols)
    return sorted(symbols)


def normalize_index(value: str) -> str:
    key = value.strip().upper().replace("-", " ").replace("_", " ")
    compact = key.replace(" ", "")
    return INDEX_ALIASES.get(key) or INDEX_ALIASES.get(compact) or compact


def index_display_name(value: str) -> str:
    return INDEX_DISPLAY_NAMES.get(normalize_index(value), value.strip().upper())


def index_constituents(value: str) -> tuple[NiftyConstituent, ...] | None:
    return INDEX_CONSTITUENTS.get(normalize_index(value))


def normalize_sector(value: str) -> str:
    return value.strip().upper().replace(" ", "_").replace("-", "_")
