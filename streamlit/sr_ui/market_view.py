"""Radar's Market View. Country shapes are bundled public Natural Earth geometry; city markets with coordinates
(APP.V_UI_CITY_SHARE) are drawn as points on top."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from sr_ui import charts, format as fmt

if TYPE_CHECKING:
    from sr_ui import data

MODES = ("Share", "Movement", "Value")
UNAVAILABLE = "#d9e1e3"
MINT = "#dcefe8"
AMBER = "#b9904d"
SHARE_LOW = "#aad5ca"


@lru_cache(maxsize=1)
def world() -> dict:
    topology = json.loads(Path(__file__).with_name("world_countries_110m.json").read_text(encoding="utf-8"))
    countries = topology["objects"]["countries"]
    countries["geometries"] = [
        shape for shape in countries["geometries"] if shape["properties"]["name"] != "Antarctica"
    ]
    return topology


def market_feature(run: data.Run) -> dict | None:
    """Use the scoped national total's first stored ranked finding, with no roll-up from its children."""
    from sr_ui import data

    if run.scope_key != data.scope_key():
        return None
    parent = data.cfg("SCOPE_PARENT_MARKET")
    if not parent:
        return None
    name = data.total_market_name(parent)
    if not name:
        return None
    # The existing All India market is documented in tests/local/synthetic.py.
    # Other national totals must match an exact country name from the bundled geography.
    country = "India" if name.strip().casefold() == "all india" else name.strip()
    shape = next((g for g in world()["objects"]["countries"]["geometries"]
                  if g.get("id") and g["properties"]["name"].casefold() == country.casefold()), None)
    if shape is None:
        return None

    category = data.cfg("SCOPE_CATEGORY")
    shifts = data.shifts(run.run_id)
    national = shifts[(shifts.MARKET_ID == parent) & (shifts.CATEGORY == category)]
    if national.empty:
        return None
    row = national.iloc[0]
    warnings = data.watchlist(run.run_id)
    matching = warnings[(warnings.MARKET_ID == parent) & (warnings.BRAND == row.BRAND)
                        & (warnings.CATEGORY == row.CATEGORY)]
    early = None
    if not matching.empty:
        warning = matching.iloc[0]
        driver = {"DIST_DROP": "Distribution", "PRICE_RISE": "Price index"}.get(warning.SIGNAL, "Driver")
        early = driver
        if pd.notna(warning.LEVER_CHG):
            early += f" {fmt.signed_pct(float(warning.LEVER_CHG))} vs last four weeks"
        if pd.notna(warning.PROJECTED_SHARE_PTS):
            early += f" · {fmt.pts(warning.PROJECTED_SHARE_PTS)} projected, next 4 weeks"

    status = {"MARKET_MOVE": "Market move", "MIXED": "Mixed signals",
              "POSSIBLE_DATA_EFFECT": "Possible data effect · held for checks"}
    share, prior, movement, value = (float(row[k]) if pd.notna(row[k]) else None
                                     for k in ("SH1", "SH0", "D_SHARE_PTS", "VALUE_AT_STAKE"))
    currency = data.cfg("CURRENCY") or ""
    return {
        "id": shape["id"], "market": name, "brand": fmt.name(row.BRAND), "category": str(row.CATEGORY),
        "share": share, "value": value, "movement": movement,
        "polarity": None if movement is None else "Loss" if movement < 0 else "Gain" if movement > 0 else "No change",
        "current": fmt.pct(share), "previous": fmt.pct(prior), "change": fmt.pts(movement),
        "stake": fmt.money(value, currency), "warning": early or "None recorded",
        "early": early is not None, "validation": status.get(row.ARTEFACT_LABEL, "Unavailable"),
        "comparison": fmt.CMP_TEXT.get(row.CMP_CODE, row.CMP_CODE),
        "cities": city_points(row.CMP_CODE, row.CATEGORY, row.BRAND, currency),
    }


def city_points(cmp_code: str, category: str, brand: str, currency: str) -> list[dict]:
    """One point per city market with coordinates; empty when the source has no city level."""
    from sr_ui import data

    try:
        cities = data.city_shares(cmp_code, category, brand)
    except Exception:                    # older deployments without V_UI_CITY_SHARE: countries only
        return []
    points = []
    for c in cities.itertuples():
        share, prior, value = (float(v) if pd.notna(v) else None for v in (c.SH1, c.SH0, c.VALUE_AT_STAKE))
        movement = float(c.D_SHARE) * 100 if pd.notna(c.D_SHARE) else None
        points.append({
            "lat": float(c.LATITUDE), "lon": float(c.LONGITUDE), "city": c.CITY, "region": c.REGION, "state": c.STATE,
            "share": share, "value": value, "movement": movement, "size": abs(value or 0),
            "polarity": None if movement is None else "Loss" if movement < 0 else "Gain" if movement > 0 else "No change",
            "current": fmt.pct(share), "previous": fmt.pct(prior), "change": fmt.pts(movement),
            "stake": fmt.money(value, currency),
        })
    return points


def map_spec(feature: dict | None, mode: str, zoom: int) -> dict:
    mark = {"type": "geoshape", "stroke": "#ffffff", "strokeWidth": 0.5, "strokeJoin": "round", "clip": True}

    def tooltip(field: str, title: str) -> dict:
        return {"field": field, "type": "nominal", "title": title}

    geography = {"values": world(), "format": {"type": "topojson", "feature": "countries"}}
    layers = [{"mark": {**mark, "fill": UNAVAILABLE},
               "transform": [{"calculate": "'Unavailable for this scope and week'", "as": "availability"}],
               "encoding": {"tooltip": [tooltip("properties.name", "Country"),
                                        tooltip("availability", "Market data")]}}]
    if feature:
        if mode == "Movement":
            color = {"field": "polarity", "type": "nominal",
                     "scale": {"domain": ["Loss", "No change", "Gain"], "range": [charts.LOSS, MINT, charts.GAIN]}}
        elif mode == "Share":
            color = {"field": "share", "type": "quantitative",
                     "scale": {"domain": [0, 1], "range": [SHARE_LOW, charts.GAIN]}}
        else:
            magnitude = abs(feature["value"] or 0) or 1
            color = {"field": "value", "type": "quantitative",
                     "scale": {"domain": [-magnitude, 0, magnitude], "range": [charts.LOSS, MINT, charts.GAIN]}}
        color["legend"] = None
        values = [("current", "Current share"), ("previous", "Previous share"),
                  ("change", "Share movement"), ("stake", "Value at stake")]
        primary = {"Share": "current", "Movement": "change", "Value": "stake"}[mode]
        values.sort(key=lambda item: item[0] != primary)
        layers.append({
            "transform": [{"filter": {"field": "id", "equal": feature["id"]}},
                          {"lookup": "id", "from": {"data": {"values": [{k: v for k, v in feature.items() if k != "cities"}]},
                                                   "key": "id",
                                                   "fields": [key for key in feature if key not in ("id", "cities")]}}],
            "mark": mark,
            "encoding": {
                "fill": {"condition": {"test": f"isValid(datum.{color['field']})", **color}, "value": UNAVAILABLE},
                "stroke": {"value": AMBER if feature["early"] else "#ffffff"},
                "strokeWidth": {"value": 1.4 if feature["early"] else 0.7},
                "tooltip": [tooltip(field, title) for field, title in
                            [("market", "Market"), ("brand", "Brand"), ("category", "Category"), *values,
                             ("warning", "Early warning"), ("validation", "Data status"),
                             ("comparison", "Comparison")]],
            },
        })
    cities = (feature or {}).get("cities") or []
    if cities:
        # City circles: area shows value at stake, fill uses the same metric colours as the country layer
        magnitude = max(abs(c["value"] or 0) for c in cities) or 1
        if mode == "Movement":
            dot = {"field": "polarity", "type": "nominal",
                   "scale": {"domain": ["Loss", "No change", "Gain"], "range": [charts.LOSS, MINT, charts.GAIN]}}
        elif mode == "Share":
            dot = {"field": "share", "type": "quantitative", "scale": {"domain": [0, max(c["share"] or 0 for c in cities) or 1],
                                                                          "range": [SHARE_LOW, charts.GAIN]}}
        else:
            dot = {"field": "value", "type": "quantitative",
                   "scale": {"domain": [-magnitude, 0, magnitude], "range": [charts.LOSS, MINT, charts.GAIN]}}
        dot["legend"] = None
        values = [("current", "Current share"), ("previous", "Previous share"),
                  ("change", "Share movement"), ("stake", "Value at stake")]
        primary = {"Share": "current", "Movement": "change", "Value": "stake"}[mode]
        values.sort(key=lambda item: item[0] != primary)
        city_layer = {
            "data": {"values": cities},
            "mark": {"type": "circle", "stroke": "#ffffff", "strokeWidth": 1, "opacity": 0.9},
            "encoding": {
                "longitude": {"field": "lon", "type": "quantitative"},
                "latitude": {"field": "lat", "type": "quantitative"},
                "size": {"field": "size", "type": "quantitative", "legend": None,
                         "scale": {"domain": [0, magnitude], "range": [40, 420]}},
                "fill": {"condition": {"test": f"isValid(datum.{dot['field']})", **dot}, "value": UNAVAILABLE},
                "tooltip": [tooltip(field, title) for field, title in
                            [("city", "City"), ("state", "State"), ("region", "Region"), *values]],
            },
        }
    projection = {"type": "equalEarth"}
    if cities:
        # Centre on India so the city points are readable; zoom steps scale from there
        projection = {"type": "mercator", "center": [80.5, 22.5],
                      "scale": {"expr": f"min(width, height * 1.25) * 1.45 * {1 + .35 * zoom}"},
                      "translate": {"expr": "[width / 2, height / 2]"}}
    elif zoom:
        # Fit against the land bounds without Antarctica, with more latitude north of the equator.
        projection.update(scale={"expr": f"min(width / 5.52, height / 2.36) * {1 + .25 * zoom}"},
                          translate={"expr": "[width / 2, height * .56]"})
    # Inline geometry stays inside the layer so Streamlit does not treat the TopoJSON object as a table.
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container", "height": 100, "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        "projection": projection,
        "layer": [{"data": geography, "layer": layers}, *([city_layer] if cities else [])],
        "config": {"background": "#ffffff", "view": {"stroke": None}},
        "usermeta": {"embedOptions": {"renderer": "svg"}},
    }
