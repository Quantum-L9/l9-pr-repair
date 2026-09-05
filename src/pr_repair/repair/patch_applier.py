# --- L9_META ---
# l9_schema: 1
# origin: pr_repair_pipeline
# engine: pr_repair
# layer: [repair]
# tags: [patch, apply, filesystem]
# owner: platform
# status: active
# --- /L9_META ---

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


def _resolve_within_root(root: Path, file_path: str) -> Path:
    """Resolve ``file_path`` against ``root`` and assert it stays inside ``root``.

    ``file_path`` originates from the (untrusted) review payload, so joining it
    onto ``root`` unchecked allows path traversal (``../``) or absolute-path
    escape outside the repository -- the vulnerability flagged by SonarCloud
    ``pythonsecurity:S2083`` ("Change this code to not construct the path from
    user-controlled data"). We canonicalize both the root and the target and
    require the target to be contained within the root before any read/write,
    while still allowing every valid repo-relative path.
    """
    root_resolved = root.resolve()
    target = (root_resolved / file_path).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        msg = f"patch target escapes repository root: {file_path}"
        raise ValueError(msg)
    return target


def _assert_within_root(root: Path, target: Path) -> None:
    """Raise unless the already-resolved ``target`` lies inside ``root``."""
    root_resolved = root.resolve()
    resolved = target.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        msg = f"patch target escapes repository root: {target}"
        raise ValueError(msg)


class PatchApplyResult(NamedTuple):
    modified_files: list[str]
    applied_finding_ids: list[str]


def _instruction_finding_id(instruction: dict[str, object]) -> str | None:
    finding_id = instruction.get("finding_id")
    if isinstance(finding_id, str) and finding_id:
        return finding_id
    return None


def apply_patch_instructions(
    instructions: list[dict[str, object]],
    repo_root: Path | None = None,
) -> PatchApplyResult:
    """Apply supported patch instructions.

    Returns modified repo-relative paths **and** the finding ids that
    actually applied. Callers must not infer applied findings from
    ``modified_files`` (two findings can share a path).
    """
    root = repo_root or Path.cwd()
    modified: list[str] = []
    applied_ids: list[str] = []
    seen_ids: set[str] = set()

    for instruction in instructions:
        op = instruction.get("op")
        if op == "replace_line":
            file_path = _apply_replace_line(instruction, root)
        elif op == "replace_range":
            file_path = _apply_replace_range(instruction, root)
        else:
            msg = f"unsupported patch op: {op}"
            raise ValueError(msg)
        modified.append(file_path)
        finding_id = _instruction_finding_id(instruction)
        if finding_id is not None and finding_id not in seen_ids:
            seen_ids.add(finding_id)
            applied_ids.append(finding_id)

    return PatchApplyResult(modified_files=sorted(set(modified)), applied_finding_ids=applied_ids)


def _apply_replace_line(instruction: dict[str, object], root: Path) -> str:
    file_path = instruction.get("file_path")
    line_number = instruction.get("line_number")
    expected = instruction.get("expected")
    replacement = instruction.get("replacement")
    if not isinstance(file_path, str) or not file_path:
        raise ValueError("instruction missing file_path")
    if not isinstance(line_number, int) or line_number < 1:
        raise ValueError("instruction missing valid line_number")
    if not isinstance(expected, str):
        raise TypeError("instruction missing expected content")
    if not isinstance(replacement, str):
        raise TypeError("instruction missing replacement content")

    path = _resolve_within_root(root, file_path)
    lines = _read_lines(path, file_path)
    if line_number > len(lines):
        msg = f"line_number {line_number} out of range for {file_path}"
        raise ValueError(msg)
    current = lines[line_number - 1]
    if current != expected:
        msg = (
            f"expected line mismatch for {file_path}:{line_number}; "
            f"found={current!r} expected={expected!r}"
        )
        raise ValueError(msg)

    lines[line_number - 1] = replacement
    _write_lines(path, lines, root=root)
    return file_path


def _apply_replace_range(instruction: dict[str, object], root: Path) -> str:
    file_path = instruction.get("file_path")
    line_start = instruction.get("line_start")
    line_end = instruction.get("line_end")
    expected_block = instruction.get("expected_block")
    replacement = instruction.get("replacement")
    if not isinstance(file_path, str) or not file_path:
        raise ValueError("instruction missing file_path")
    if not isinstance(line_start, int) or line_start < 1:
        raise ValueError("instruction missing valid line_start")
    if not isinstance(line_end, int) or line_end < line_start:
        raise ValueError("instruction missing valid line_end")
    if not isinstance(replacement, str):
        raise TypeError("instruction missing replacement content")

    path = _resolve_within_root(root, file_path)
    lines = _read_lines(path, file_path)
    if line_end > len(lines):
        msg = f"line range {line_start}-{line_end} out of range for {file_path}"
        raise ValueError(msg)

    # Exact-match guard: the on-disk block must match what the finding was generated
    # against. No fuzzy matching -- drift aborts the patch.
    #
    # ``expected_block`` is MANDATORY, matching ``_apply_replace_line``'s treatment
    # of ``expected``. It was previously checked only when present, so an
    # instruction that simply omitted it overwrote a model-chosen line range with
    # no content verification at all. The deterministic generator always attaches
    # the block; the LLM proposer, the least trustworthy source, was the one path
    # that did not -- so the guard was absent exactly where it was needed most.
    # Refuse rather than infer: an instruction that cannot say what it expects to
    # replace has no business replacing it.
    if expected_block is None:
        msg = (
            f"replace_range requires expected_block for {file_path}:"
            f"{line_start}-{line_end}; refusing unguarded range replacement"
        )
        raise ValueError(msg)
    if not isinstance(expected_block, list):
        raise TypeError("expected_block must be a list of lines")
    current_block = lines[line_start - 1 : line_end]
    if current_block != expected_block:
        msg = (
            f"expected block mismatch for {file_path}:{line_start}-{line_end}; "
            f"found={current_block!r} expected={expected_block!r}"
        )
        raise ValueError(msg)

    lines[line_start - 1 : line_end] = replacement.split("\n")
    _write_lines(path, lines, root=root)
    return file_path


def _read_lines(path: Path, file_path: str) -> list[str]:
    if not path.exists():
        msg = f"target file does not exist: {file_path}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: list[str], *, root: Path) -> None:
    """Write ``lines`` to ``path``, re-proving containment at the point of write.

    Callers already resolve through :func:`_resolve_within_root`, so this repeats
    a check that has passed. That is deliberate: this is the only function in the
    module that mutates the filesystem, and every byte it writes originates in an
    untrusted review payload. Binding the guarantee to the write itself means a
    future caller cannot reach it without containment, rather than the guarantee
    resting on each caller having remembered to validate first.
    """
    _assert_within_root(root, path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
