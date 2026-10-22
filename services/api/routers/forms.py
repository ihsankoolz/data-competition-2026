"""Request form specs (PRD M3), rendered by the web app from config JSON Schema."""

from fastapi import APIRouter, HTTPException

from ds.forms import (
    FORM_DOMAINS,
    extract_to_form_field,
    load_form_schema,
    regulated_countries,
    required_keys,
)
from services.api.schemas import CountryCode, Domain, FormSpec

router = APIRouter(tags=["forms"])


@router.get("/forms/{domain}", response_model=FormSpec, operation_id="getForm")
def get_form(domain: Domain, country: CountryCode | None = None) -> FormSpec:
    if domain not in FORM_DOMAINS:
        raise HTTPException(status_code=404, detail=f"There is no request form for {domain} yet.")
    schema = load_form_schema(domain)
    to_field = extract_to_form_field(domain)
    keys = required_keys(domain, country, include_form_only=True)
    required = sorted({to_field[k] for k in keys if k in to_field}, key=schema["x-order"].index)
    spec = FormSpec(domain=domain, country=country, json_schema=schema, required=required)
    if domain == "item":
        spec.required_per_selling_country = ["reg_no"]
        spec.regulated_countries = regulated_countries()
    return spec
