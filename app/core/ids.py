import hashlib


def build_item_id(plugin_name: str, canonical_url: str) -> str:
    source = f"{plugin_name}\n{canonical_url}"
    return hashlib.sha256(source.encode()).hexdigest()

