#!/usr/bin/env python3
"""portals_config: load/save portals.yml for the TUI editor screen.

Preserves any keys this editor doesn't touch (e.g. location_filter) by
round-tripping the full loaded dict.
"""
import os

import yaml


def load_portals(path):
    if not os.path.exists(path):
        data = {}
    else:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data.setdefault("title_filter", {})
    data["title_filter"].setdefault("positive", [])
    data["title_filter"].setdefault("negative", [])
    data.setdefault("location_filter", {})
    data["location_filter"].setdefault("always_allow", [])
    data["location_filter"].setdefault("block", [])
    data["location_filter"].setdefault("allow", [])
    data.setdefault("tracked_companies", [])
    data.setdefault("jobspy", {})
    data["jobspy"].setdefault("enabled", False)
    data["jobspy"].setdefault("sites", [])
    data["jobspy"].setdefault("results_wanted", 20)
    data["jobspy"].setdefault("country_indeed", "usa")
    data["jobspy"].setdefault("location", "")
    return data


def save_portals(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
