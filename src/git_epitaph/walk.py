"""Replay history oldest-first and keep a ledger of who is alive, who died, who came back."""

from __future__ import annotations

from dataclasses import dataclass, field

from git_epitaph.gitlog import Commit

DAY = 86400


@dataclass
class Birth:
    path: str
    ts: int
    sha: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Grave:
    path: str  # name at time of death
    born_path: str  # name at birth (differs after renames)
    born: int | None  # None when the file predates available history
    born_sha: str | None
    died: int
    died_sha: str
    killer: str  # author of the deleting commit
    epitaph: str  # subject of the deleting commit
    lines: int | None  # lines at death; None for binaries
    risen: bool = False  # re-added under the same path later in history
    aliases: list[str] = field(default_factory=list)

    @property
    def age_days(self) -> int | None:
        if self.born is None:
            return None
        return (self.died - self.born) // DAY


def bury(commits: list[Commit]) -> list[Grave]:
    """Return every death in `commits` (oldest-first), in death order."""
    alive: dict[str, Birth] = {}
    graves: list[Grave] = []
    last_grave_for: dict[str, Grave] = {}

    for c in commits:
        for ch in c.changes:
            if ch.status == "A":
                if ch.path in last_grave_for:
                    last_grave_for.pop(ch.path).risen = True
                alive[ch.path] = Birth(ch.path, c.ts, c.sha)
            elif ch.status == "C":
                alive[ch.path] = Birth(ch.path, c.ts, c.sha)
            elif ch.status == "R":
                if ch.old_path is None:
                    raise ValueError(f"rename without old path in {c.sha}: {ch.path}")
                birth = alive.pop(ch.old_path, None)
                if birth is None:
                    birth = Birth(ch.old_path, c.ts, c.sha)
                birth.aliases.append(ch.old_path)
                alive[ch.path] = birth
            elif ch.status == "D":
                birth = alive.pop(ch.path, None)
                grave = Grave(
                    path=ch.path,
                    born_path=birth.path if birth else ch.path,
                    born=birth.ts if birth else None,
                    born_sha=birth.sha if birth else None,
                    died=c.ts,
                    died_sha=c.sha,
                    killer=c.author,
                    epitaph=c.subject,
                    lines=c.deleted_lines.get(ch.path),
                    aliases=list(birth.aliases) if birth else [],
                )
                graves.append(grave)
                last_grave_for[ch.path] = grave
    return graves
