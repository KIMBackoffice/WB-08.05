# src/utils.py

import re

def normalize_name(name):
    if not name:
        return None
    return str(name).lower().strip()


def format_name(full_name):
    if not full_name:
        return None

    parts = str(full_name).split()
    if len(parts) < 2:
        return parts[0]

    return f"{parts[0][0]}. {parts[-1]}"
