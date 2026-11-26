"""Git numstat and untracked file SLOC delta helpers."""

from pathlib import Path
from typing import List, Set, Tuple

from tools.brigade.fsm_ops.spec_files import _is_non_prod_file


def _process_numstat_lines(
    numstat_out: str,
    target_file_norm: str,
) -> Tuple[Set[str], int, int, bool]:
    seen: Set[str] = set()
    t_found = False
    t_delta = 0
    net = 0

    for line in numstat_out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            continue
        ins_s, del_s, raw_fn = parts[0], parts[1], parts[2].replace("\\", "/").strip()
        fn = raw_fn[2:] if raw_fn.startswith("./") else raw_fn
        seen.add(fn)
        if not (ins_s.isdigit() and del_s.isdigit()):
            continue
        ins, dels = int(ins_s), int(del_s)
        if target_file_norm and fn == target_file_norm:
            t_found = True
            t_delta = ins - dels
        if not _is_non_prod_file(fn):
            net += (ins - dels)

    return seen, t_delta, net, t_found


def _count_untracked_prod_lines(
    prod_changed_files: List[str],
    seen_files: Set[str],
    target_file_norm: str,
    eff_dir: Path,
) -> Tuple[int, int, bool]:
    net = 0
    t_delta = 0
    t_found = False

    for pf in prod_changed_files:
        if pf in seen_files:
            continue
        fpath = eff_dir / pf
        if not (fpath.exists() and fpath.is_file()):
            continue
        try:
            cnt = len(fpath.read_text(encoding="utf-8", errors="ignore").splitlines())
            net += cnt
            if target_file_norm and pf == target_file_norm:
                t_found = True
                t_delta = cnt
        except Exception:
            pass

    return net, t_delta, t_found


def _compute_sloc_deltas(
    numstat_out: str,
    prod_changed_files: List[str],
    target_file_norm: str,
    eff_dir: Path,
) -> Tuple[int, int, bool]:
    seen, t_delta, net, t_found = _process_numstat_lines(numstat_out, target_file_norm)
    u_net, u_delta, u_found = _count_untracked_prod_lines(
        prod_changed_files, seen, target_file_norm, eff_dir
    )
    final_target_found = t_found or u_found
    final_target_delta = t_delta if t_found else u_delta
    final_net = net + u_net
    return final_target_delta, final_net, final_target_found
