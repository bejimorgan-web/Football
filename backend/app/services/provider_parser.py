from __future__ import annotations

from typing import Dict, List

from app.logo_utils import normalize_logo_url


def normalize_groups(raw_groups: List[Dict[str, object]], raw_channels: List[Dict[str, object]]) -> List[Dict[str, object]]:
    groups: Dict[str, Dict[str, object]] = {}

    for group in raw_groups or []:
        group_id = str(group.get("id") or group.get("group_id") or group.get("category_id") or "").strip()
        group_name = str(group.get("name") or group.get("group_name") or group.get("category_name") or "").strip() or "Ungrouped"
        normalized_id = group_id or group_name.lower().replace(" ", "-")
        groups[normalized_id] = {
            "id": normalized_id,
            "group_id": normalized_id,
            "name": group_name,
            "channel_count": int(group.get("channel_count") or 0),
            "channels": [],
        }

    for channel in raw_channels or []:
        group_id = str(channel.get("group_id") or channel.get("category_id") or "").strip()
        if not group_id:
            group_name = str(channel.get("group") or channel.get("category_name") or "Ungrouped").strip() or "Ungrouped"
            group_id = group_name.lower().replace(" ", "-")
            groups.setdefault(
                group_id,
                {
                    "id": group_id,
                    "group_id": group_id,
                    "name": group_name,
                    "channel_count": 0,
                    "channels": [],
                },
            )

        if group_id not in groups:
            groups[group_id] = {
                "id": group_id,
                "group_id": group_id,
                "name": str(channel.get("group") or channel.get("category_name") or "Ungrouped").strip() or "Ungrouped",
                "channel_count": 0,
                "channels": [],
            }

        groups[group_id]["channels"].append(
            {
                "id": str(channel.get("id") or channel.get("channel_id") or channel.get("stream_id") or "").strip(),
                "name": str(channel.get("name") or channel.get("channel_name") or "Unnamed channel").strip() or "Unnamed channel",
                "logo": normalize_logo_url(channel.get("logo") or channel.get("stream_icon") or ""),
                "stream_id": str(channel.get("stream_id") or channel.get("id") or channel.get("channel_id") or "").strip(),
                "group_id": group_id,
                "stream_url": str(channel.get("stream_url") or channel.get("url") or "").strip(),
            }
        )

    normalized_groups = list(groups.values())
    for group in normalized_groups:
        channels = list(group.get("channels") or [])
        channels.sort(key=lambda item: str(item.get("name") or "").lower())
        group["channels"] = channels
        group["channel_count"] = len(channels)

    normalized_groups.sort(key=lambda item: str(item.get("name") or "").lower())
    return normalized_groups
