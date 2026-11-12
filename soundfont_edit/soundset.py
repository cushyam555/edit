"""Pure operations on destination entries; cancellation never changes the input."""


def slot(entry):
    return int(entry["bank"]), int(entry["program"])


def ordered(entries):
    return sorted(
        entries, key=lambda e: (e["bank"] == 128, *slot(e), e["name"].casefold())
    )


def copy_entry(entry):
    return dict(
        entry,
        source_bank=entry.get("source_bank", entry["bank"]),
        source_program=entry.get("source_program", entry["program"]),
    )


def merge_entries(existing, incoming, resolve):
    """resolve(candidate, conflicting, working) -> (replace/remap/cancel, new slot)."""
    working = [copy_entry(e) for e in existing]
    for entry in incoming:
        candidate = copy_entry(entry)
        while True:
            bank, program = slot(candidate)
            if not 0 <= bank <= 128 or not 0 <= program <= 127:
                raise ValueError("Bank must be 0–128 and ID 0–127")
            match = next(
                (i for i, e in enumerate(working) if slot(e) == slot(candidate)), None
            )
            if match is None:
                working.append(candidate)
                break
            action, value = resolve(candidate, working[match], working)
            if action == "cancel":
                return None
            if action == "replace":
                working[match] = candidate
                break
            if action != "remap" or value is None:
                raise ValueError("Invalid conflict resolution")
            candidate = dict(candidate, bank=value[0], program=value[1])
    return ordered(working)
