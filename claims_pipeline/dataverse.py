"""Dataverse Web API client for DAG D (Snowflake CURATED -> Dataverse).

Auth is OAuth 2.0 client credentials against Entra ID; credentials come from
environment variables only. The Claim table is created from code (schema as
code) so the environment can be rebuilt without portal clicking. The sync
upserts the source columns and never touches the app-owned decision columns,
so a specialist's decision survives a re-sync.

    python -m claims_pipeline.dataverse create-table
    python -m claims_pipeline.dataverse sync
"""
from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

API_PATH = "/api/data/v9.2"
TABLE_SUFFIX = "claim"
SOURCE_VIEW = os.environ.get("DATAVERSE_SOURCE_VIEW", "CURATED.V_CLAIM_ASSESSMENT")
WORKERS = 8  # concurrent upserts; 429 throttling is retried in _request

# (Snowflake column, Dataverse attribute suffix, kind). SRC_ROW_ID is the primary name column.
SOURCE_COLUMNS = [
    ("SRC_ROW_ID", "srcrowid", "string"),
    ("VEH_BODY", "vehbody", "string"),
    ("GENDER", "gender", "string"),
    ("AGECAT", "agecat", "int"),
    ("DRIVER_AGE_BAND", "driverageband", "string"),
    ("VEH_VALUE", "vehvalue", "decimal"),
    ("EXPOSURE", "exposure", "decimal"),
    ("NUMCLAIMS", "numclaims", "int"),
    ("CLAIM_AMOUNT", "claimamount", "decimal"),
    ("POLICY_START_DATE", "policystartdate", "date"),
    ("POLICY_END_DATE", "policyenddate", "date"),
    ("LOSS_DATE", "lossdate", "date"),
    ("RECOMMENDED_OUTCOME", "recommendedoutcome", "string"),
    ("CITED_CLAUSES", "citedclauses", "memo"),
    ("CONDITIONS", "conditions", "memo"),
]

# Claim Note table: free-text notes and status-change history entered in the canvas app.
NOTE_TABLE_SUFFIX = "claimnote"
NOTE_COLUMNS = [
    ("claimkey", "string"),  # the claim's srcrowid
    ("body", "memo"),
    ("author", "string"),
    ("kind", "string"),  # "Note" or "Status change"
]

# Agent results, written by the Agent API: (display, plural, description, primary column, columns).
AGENT_TABLES = {
    "claimassessment": (
        "Claim Assessment", "Claim Assessments", "AI assessment of a claim against the PDS", "headline",
        [("claimkey", "string"), ("outcome", "string"), ("summary", "memo"), ("clauses", "string"),
         ("pdsversion", "string"), ("model", "string")],
    ),
    "decisioncheck": (
        "Decision Check", "Decision Checks", "Independent check of a submitted decision against the PDS", "headline",
        [("claimkey", "string"), ("decision", "string"), ("agrees", "bool"), ("reasonsupported", "bool"),
         ("requiresmanager", "bool"), ("correctoutcome", "string"), ("finding", "memo"), ("clauses", "string"),
         ("pdsversion", "string"), ("model", "string")],
    ),
}

# Written by the canvas app (accept / decline / override). The sync never sends these.
APP_COLUMNS = [
    ("decision", "string"),
    ("decisionreason", "memo"),
    ("decidedby", "string"),
    ("decidedat", "datetime"),
]


# Display names shown by the canvas app and model-driven views (keyed by attribute suffix).
LABELS = {
    "srcrowid": "Source row ID", "vehbody": "Vehicle body", "gender": "Gender", "agecat": "Age category",
    "driverageband": "Driver age band", "vehvalue": "Vehicle value ($10k)", "exposure": "Exposure (years)",
    "numclaims": "Number of claims", "claimamount": "Claim amount ($)", "policystartdate": "Policy start",
    "policyenddate": "Policy end", "lossdate": "Loss date", "recommendedoutcome": "Rules outcome",
    "citedclauses": "Cited clauses", "conditions": "Conditions", "decision": "Decision",
    "decisionreason": "Decision reason", "decidedby": "Decided by", "decidedat": "Decided at",
    "summary": "Summary", "claimkey": "Claim key", "body": "Note", "author": "Author", "kind": "Type",
    "headline": "Headline", "outcome": "Outcome", "clauses": "Clauses", "pdsversion": "PDS version",
    "model": "Model", "agrees": "Agrees with PDS", "reasonsupported": "Reason supported",
    "requiresmanager": "Requires line manager", "correctoutcome": "Correct outcome", "finding": "Finding",
}

# Source codes -> readable values for the case record (Snowflake keeps the raw codes).
VEHICLE_BODY = {
    "BUS": "Bus", "CONVT": "Convertible", "COUPE": "Coupe", "HBACK": "Hatchback", "HDTOP": "Hardtop",
    "MCARA": "Motorised caravan", "MIBUS": "Minibus", "PANVN": "Panel van", "RDSTR": "Roadster",
    "SEDAN": "Sedan", "STNWG": "Station wagon", "TRUCK": "Truck", "UTE": "Utility",
}
GENDER = {"M": "Male", "F": "Female"}

# Metadata type used to read/update each kind of column.
ATTRIBUTE_TYPES = {
    "string": "StringAttributeMetadata", "memo": "MemoAttributeMetadata", "int": "IntegerAttributeMetadata",
    "decimal": "DecimalAttributeMetadata", "date": "DateTimeAttributeMetadata",
    "datetime": "DateTimeAttributeMetadata", "bool": "BooleanAttributeMetadata",
}


def display_value(suffix: str, value):
    """Readable form of a code for the case record (vehicle body, gender, age band)."""
    if not isinstance(value, str):
        return value
    if suffix == "vehbody":
        return VEHICLE_BODY.get(value.upper(), value.title())
    if suffix == "gender":
        return GENDER.get(value.upper(), value)
    if suffix == "driverageband":
        return value.title()
    return value


@dataclass(frozen=True)
class DataverseConfig:
    url: str
    tenant_id: str
    client_id: str
    client_secret: str
    prefix: str | None = None

    @classmethod
    def from_env(cls) -> DataverseConfig:
        return cls(
            url=os.environ["DATAVERSE_URL"].rstrip("/"),
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
            prefix=os.environ.get("DATAVERSE_PREFIX") or None,
        )


def to_record(row: dict, prefix: str) -> dict:
    """Map one Snowflake row (column -> value) to a Dataverse record."""
    record = {}
    for column, suffix, kind in SOURCE_COLUMNS:
        value = row.get(column)
        if value is not None:
            if kind == "decimal":
                value = float(Decimal(value))
            elif kind == "int":
                value = int(value)
            elif kind == "date" and isinstance(value, (date, datetime)):
                value = value.strftime("%Y-%m-%d")
            else:
                value = display_value(suffix, value)
        record[f"{prefix}_{suffix}"] = value
    return record


def _label(text: str) -> dict:
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.Label",
        "LocalizedLabels": [
            {"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel", "Label": text, "LanguageCode": 1033}
        ],
    }


def attribute_metadata(schema_name: str, display: str, kind: str) -> dict:
    base = {"SchemaName": schema_name, "DisplayName": _label(display), "RequiredLevel": {"Value": "None"}}
    if kind == "string":
        return {"@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata", "MaxLength": 200,
                "FormatName": {"Value": "Text"}, **base}
    if kind == "memo":
        return {"@odata.type": "Microsoft.Dynamics.CRM.MemoAttributeMetadata", "MaxLength": 4000,
                "Format": "TextArea", **base}
    if kind == "int":
        return {"@odata.type": "Microsoft.Dynamics.CRM.IntegerAttributeMetadata", "Format": "None",
                "MinValue": -2147483648, "MaxValue": 2147483647, **base}
    if kind == "decimal":
        return {"@odata.type": "Microsoft.Dynamics.CRM.DecimalAttributeMetadata", "Precision": 4,
                "MinValue": -100000000000.0, "MaxValue": 100000000000.0, **base}
    if kind == "date":
        return {"@odata.type": "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata", "Format": "DateOnly",
                "DateTimeBehavior": {"Value": "DateOnly"}, **base}
    if kind == "datetime":
        return {"@odata.type": "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata", "Format": "DateAndTime",
                "DateTimeBehavior": {"Value": "UserLocal"}, **base}
    if kind == "bool":
        return {"@odata.type": "Microsoft.Dynamics.CRM.BooleanAttributeMetadata", "OptionSet": {
                    "@odata.type": "Microsoft.Dynamics.CRM.BooleanOptionSetMetadata",
                    "TrueOption": {"Value": 1, "Label": _label("Yes")},
                    "FalseOption": {"Value": 0, "Label": _label("No")}}, **base}
    raise ValueError(f"unknown attribute kind: {kind}")


class DataverseClient:
    def __init__(self, config: DataverseConfig):
        self.config = config
        self.base = config.url + API_PATH
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {self._token()}", "OData-Version": "4.0",
             "Accept": "application/json", "Content-Type": "application/json"}
        )
        self._prefix = config.prefix

    def _token(self) -> str:
        resp = requests.post(
            f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": self.config.client_id,
                  "client_secret": self.config.client_secret, "scope": f"{self.config.url}/.default"},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"token request failed: {resp.status_code} {resp.json().get('error_description', '')[:200]}")
        return resp.json()["access_token"]

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self.base + path if path.startswith("/") else path
        for attempt in range(6):
            resp = self.session.request(method, url, timeout=60, **kwargs)
            # 429 is service-protection throttling (or a customization lock): wait and retry
            if resp.status_code == 429 and attempt < 5:
                time.sleep(min(int(resp.headers.get("Retry-After", 5)), 60))
                continue
            break
        if not resp.ok and resp.status_code != 404:
            raise RuntimeError(f"{method} {path} -> {resp.status_code} {resp.text[:300]}")
        return resp

    @property
    def prefix(self) -> str:
        if not self._prefix:
            resp = self._request(
                "GET", "/publishers?$select=customizationprefix&$filter=startswith(uniquename,'DefaultPublisher')")
            self._prefix = resp.json()["value"][0]["customizationprefix"]
        return self._prefix

    @property
    def logical_name(self) -> str:
        return f"{self.prefix}_{TABLE_SUFFIX}"

    def entity_set(self) -> str | None:
        resp = self._request("GET", f"/EntityDefinitions(LogicalName='{self.logical_name}')?$select=EntitySetName")
        return None if resp.status_code == 404 else resp.json()["EntitySetName"]

    def ensure_table(self) -> str:
        """Create the Claim table and its columns if missing. Returns the entity set name."""
        p = self.prefix
        if self.entity_set() is None:
            logger.info("creating table %s", self.logical_name)
            self._request("POST", "/EntityDefinitions", json={
                "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
                "SchemaName": self.logical_name,
                "DisplayName": _label("Claim"),
                "DisplayCollectionName": _label("Claims"),
                "Description": _label("Motor claims queue synced from Snowflake (DAG D)"),
                "OwnershipType": "UserOwned",
                "HasActivities": False,
                "HasNotes": False,
                "Attributes": [{**attribute_metadata(f"{p}_srcrowid", "Source row ID", "string"),
                                "IsPrimaryName": True, "MaxLength": 100}],
            })
        existing = {a["LogicalName"] for a in self._request(
            "GET", f"/EntityDefinitions(LogicalName='{self.logical_name}')/Attributes?$select=LogicalName"
        ).json()["value"]}
        wanted = [(f"{p}_{s}", s, k) for _, s, k in SOURCE_COLUMNS] + [(f"{p}_{s}", s, k) for s, k in APP_COLUMNS]
        for schema, suffix, kind in wanted:
            if schema.lower() in existing:
                continue
            logger.info("adding column %s", schema)
            self._request("POST", f"/EntityDefinitions(LogicalName='{self.logical_name}')/Attributes",
                          json=attribute_metadata(schema, LABELS.get(suffix, suffix), kind))
        self._apply_labels(self.logical_name, [(s, k) for _, s, k in SOURCE_COLUMNS] + APP_COLUMNS)
        self._request("POST", "/PublishAllXml", json={})
        return self.entity_set()

    def _apply_labels(self, logical: str, columns: list[tuple[str, str]]) -> None:
        """Set readable display names on existing columns (idempotent; only writes when a label differs)."""
        for suffix, kind in columns:
            want = LABELS.get(suffix)
            if not want:
                continue
            base = f"/EntityDefinitions(LogicalName='{logical}')/Attributes(LogicalName='{self.prefix}_{suffix}')"
            resp = self._request("GET", f"{base}/Microsoft.Dynamics.CRM.{ATTRIBUTE_TYPES[kind]}")
            if resp.status_code == 404:
                continue
            meta = resp.json()
            labels = (meta.get("DisplayName") or {}).get("LocalizedLabels") or []
            if labels and labels[0].get("Label") == want:
                continue
            logger.info("renaming %s_%s -> %s", self.prefix, suffix, want)
            body = attribute_metadata(f"{self.prefix}_{suffix}", want, kind)
            body["MetadataId"] = meta["MetadataId"]
            if "MaxLength" in meta:
                body["MaxLength"] = meta["MaxLength"]  # never shrink an existing column
            self._request("PUT", base, json=body, headers={"MSCRM.MergeLabels": "true"})

    def ensure_simple_table(self, suffix: str, display: str, plural: str, description: str,
                            primary_suffix: str, columns: list[tuple[str, str]]) -> str:
        """Create a small table (a text primary column plus typed columns) if missing; returns its entity set."""
        p = self.prefix
        logical = f"{p}_{suffix}"
        probe = self._request("GET", f"/EntityDefinitions(LogicalName='{logical}')?$select=EntitySetName")
        if probe.status_code == 404:
            logger.info("creating table %s", logical)
            self._request("POST", "/EntityDefinitions", json={
                "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
                "SchemaName": logical,
                "DisplayName": _label(display),
                "DisplayCollectionName": _label(plural),
                "Description": _label(description),
                "OwnershipType": "UserOwned",
                "HasActivities": False,
                "HasNotes": False,
                "Attributes": [{**attribute_metadata(f"{p}_{primary_suffix}", LABELS.get(primary_suffix, primary_suffix),
                                                     "string"), "IsPrimaryName": True, "MaxLength": 200}],
            })
        existing = {a["LogicalName"] for a in self._request(
            "GET", f"/EntityDefinitions(LogicalName='{logical}')/Attributes?$select=LogicalName"
        ).json()["value"]}
        for col, kind in columns:
            if f"{p}_{col}" in existing:
                continue
            logger.info("adding column %s_%s", p, col)
            self._request("POST", f"/EntityDefinitions(LogicalName='{logical}')/Attributes",
                          json=attribute_metadata(f"{p}_{col}", LABELS.get(col, col), kind))
        self._apply_labels(logical, columns)
        self._request("POST", "/PublishAllXml", json={})
        return self._request(
            "GET", f"/EntityDefinitions(LogicalName='{logical}')?$select=EntitySetName").json()["EntitySetName"]

    def ensure_notes_table(self) -> str:
        """Create the Claim Note table (specialist notes and status history) if missing."""
        return self.ensure_simple_table(NOTE_TABLE_SUFFIX, "Claim Note", "Claim Notes",
                                        "Specialist notes and status history for a claim", "summary", NOTE_COLUMNS)

    def ensure_agent_tables(self) -> dict[str, str]:
        """Create the tables that hold the agent's assessments and decision checks."""
        return {suffix: self.ensure_simple_table(suffix, *spec) for suffix, spec in AGENT_TABLES.items()}

    def existing_ids(self, entity_set: str) -> dict[str, str]:
        """Map source row id -> Dataverse record id for every row already present."""
        key, pk = f"{self.prefix}_srcrowid", f"{self.logical_name}id"
        found, url = {}, f"/{entity_set}?$select={key}"
        while url:
            data = self._request("GET", url).json()
            found.update({r[key]: r[pk] for r in data["value"]})
            url = data.get("@odata.nextLink")
        return found

    def upsert_claims(self, rows: list[dict]) -> dict:
        entity_set = self.entity_set() or self.ensure_table()
        ids = self.existing_ids(entity_set)
        key = f"{self.prefix}_srcrowid"

        def upsert(row: dict) -> str:
            record = to_record(row, self.prefix)
            if record[key] in ids:
                self._request("PATCH", f"/{entity_set}({ids[record[key]]})", json=record)
                return "updated"
            self._request("POST", f"/{entity_set}", json=record)
            return "created"

        stats = {"created": 0, "updated": 0, "failed": 0, "total": len(rows)}
        errors: list[str] = []

        def safe_upsert(row: dict) -> None:
            try:
                stats[upsert(row)] += 1
            except RuntimeError as exc:
                stats["failed"] += 1
                errors.append(str(exc))

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(safe_upsert, rows))
        if stats["failed"]:
            logger.error("%s rows failed; first error: %s", stats["failed"], errors[0])
        return stats


def read_queue() -> list[dict]:
    """Read the specialist queue from Snowflake as a list of {COLUMN: value} dicts."""
    import snowflake.connector

    from claims_pipeline.config import SnowflakeConfig

    with snowflake.connector.connect(**SnowflakeConfig.from_env().connect_kwargs()) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {SOURCE_VIEW}")
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, r)) for r in cur.fetchall()]


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    command = argv[1] if len(argv) > 1 else ""
    try:
        client = DataverseClient(DataverseConfig.from_env())
        if command == "create-table":
            print("entity set:", client.ensure_table())
            print("notes entity set:", client.ensure_notes_table())
            print("agent entity sets:", client.ensure_agent_tables())
        elif command == "sync":
            stats = client.upsert_claims(read_queue())
            print(stats)
            return 1 if stats["failed"] else 0
        else:
            print(__doc__)
            return 2
    except KeyError as missing:
        print(f"missing env var: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
