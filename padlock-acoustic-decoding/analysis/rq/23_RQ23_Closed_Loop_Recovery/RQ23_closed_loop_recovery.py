from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SESSION_IDS = [
    "AUTO_2475_01",
    "AUTO_3159_01",
    "AUTO_5318_01",
    "AUTO_6924_01",
    "AUTO_7642_01",
    "AUTO_9086_01",
]

RETRY_MARGIN_THRESHOLD = 0.20
DARK_BLUE = "#315B7D"
LIGHT_BLUE = "#AFC5D5"
DARK_GREY = "#596168"


def locate_recognition_root(mydrive: Path) -> Path:
    mydrive = Path(mydrive)
    candidates = [
        mydrive / "dataset" / "recognition_results",
        mydrive / "dataset" / "dataset" / "recognition_results",
        mydrive / "Padlock_Reproduction_v1" / "dataset" / "recognition_results",
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1" / "dataset" / "recognition_results",
    ]
    for root in candidates:
        if root.is_dir() and any((root / session / "AUTO_flow_report.txt").exists() for session in SESSION_IDS):
            return root

    matches = []
    for base in [mydrive / "dataset", mydrive / "Padlock_Reproduction_v1"]:
        if not base.exists():
            continue
        for report in base.rglob("AUTO_flow_report.txt"):
            if report.parent.name in SESSION_IDS:
                matches.append(report.parent.parent)
    unique = sorted({p.resolve() for p in matches})
    if len(unique) == 1:
        return unique[0]
    raise FileNotFoundError("Could not uniquely locate dataset/recognition_results containing the frozen RQ23 sessions.")


def _match_value(text: str, label: str) -> str | None:
    m = re.search(rf"^{re.escape(label)}:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_flow_report(path: Path) -> tuple[dict, list[dict]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")

    header = {
        "session": _match_value(text, "Session"),
        "outcome": _match_value(text, "Outcome"),
        "detected_code": _match_value(text, "Detected code"),
        "true_code": _match_value(text, "Post-hoc true code"),
        "posthoc_success": _match_value(text, "Post-hoc full-code success"),
        "passes_used": _match_value(text, "Passes used"),
        "report_path": str(path),
    }

    blocks = re.split(r"(?m)^PASS\s+(\d+)\s*$", text)
    passes = []
    for i in range(1, len(blocks), 2):
        pass_index = int(blocks[i])
        block = blocks[i + 1]
        if "\nFILES\n" in block:
            block = block.split("\nFILES\n", 1)[0]

        margins_text = _match_value(block, "  Margins") or _match_value(block, "Margins")
        margins = ast.literal_eval(margins_text) if margins_text else {}
        minimum_margin = _match_value(block, "  Minimum margin") or _match_value(block, "Minimum margin")

        row = {
            "session": header["session"],
            "true_code": header["true_code"],
            "pass_index": pass_index,
            "start_code": _match_value(block, "  Start code") or _match_value(block, "Start code"),
            "end_code": _match_value(block, "  End code") or _match_value(block, "End code"),
            "pass_outcome": _match_value(block, "  Outcome") or _match_value(block, "Outcome"),
            "top1_prefix": _match_value(block, "  Top-1 prefix") or _match_value(block, "Top-1 prefix"),
            "minimum_margin": float(minimum_margin) if minimum_margin is not None else np.nan,
        }
        for wheel in [1, 2, 4]:
            row[f"W{wheel}_margin"] = float(margins.get(f"W{wheel}", np.nan))
            pattern = rf"(?m)^\s*W{wheel}:\s*Top-1=(\d+)\s+Top-3=(\[[^\]]+\])\s+margin=([-+0-9.eE]+)\s*$"
            m = re.search(pattern, block)
            if m:
                row[f"W{wheel}_top1"] = int(m.group(1))
                row[f"W{wheel}_top3"] = ast.literal_eval(m.group(2))
            else:
                row[f"W{wheel}_top1"] = np.nan
                row[f"W{wheel}_top3"] = []
        passes.append(row)

    return header, passes


def _true_digit(true_code: str, wheel: int) -> int:
    index = {1: 0, 2: 1, 4: 3}[wheel]
    return int(str(true_code)[index])


def _fallback_rank_from_report(top3: list[int], true_digit: int) -> float:
    if true_digit in top3:
        return float(top3.index(true_digit) + 1)
    return np.nan


def add_exact_candidate_ranks(pass_frame: pd.DataFrame, session_dir: Path) -> pd.DataFrame:
    pass_frame = pass_frame.copy()
    evidence_path = Path(session_dir) / "MAIN_v8_candidate_evidence.csv"
    evidence = pd.read_csv(evidence_path) if evidence_path.exists() else None

    for idx, row in pass_frame.iterrows():
        true_code = str(row["true_code"])
        p = int(row["pass_index"])
        for wheel in [1, 2, 4]:
            true_digit = _true_digit(true_code, wheel)
            exact_rank = np.nan
            if evidence is not None:
                expected_profile = f"AUTO_{row['session']}_P{p}_W{wheel}"
                sub = evidence[
                    evidence["profile_id"].astype(str).eq(expected_profile)
                    & evidence["digit"].astype(int).eq(true_digit)
                ]
                if len(sub) == 1:
                    exact_rank = float(sub.iloc[0]["fused_rank"])
            if np.isnan(exact_rank):
                exact_rank = _fallback_rank_from_report(row[f"W{wheel}_top3"], true_digit)
            pass_frame.at[idx, f"W{wheel}_true_rank"] = exact_rank
            pass_frame.at[idx, f"W{wheel}_true_in_top2"] = bool(not np.isnan(exact_rank) and exact_rank <= 2)
            pass_frame.at[idx, f"W{wheel}_true_in_top3"] = bool(not np.isnan(exact_rank) and exact_rank <= 3)
            pass_frame.at[idx, f"W{wheel}_top1_correct"] = bool(int(row[f"W{wheel}_top1"]) == true_digit)

        pass_frame.at[idx, "full_prefix_top1_correct"] = all(
            bool(pass_frame.at[idx, f"W{wheel}_top1_correct"]) for wheel in [1, 2, 4]
        )
        pass_frame.at[idx, "static_top2_prefix_covered"] = all(
            bool(pass_frame.at[idx, f"W{wheel}_true_in_top2"]) for wheel in [1, 2, 4]
        )
        pass_frame.at[idx, "static_top3_prefix_covered"] = all(
            bool(pass_frame.at[idx, f"W{wheel}_true_in_top3"]) for wheel in [1, 2, 4]
        )
        unlocked = str(row["pass_outcome"]).startswith("UNLOCKED")
        pass_frame.at[idx, "physical_unlock"] = bool(unlocked)
        pass_frame.at[idx, "low_margin"] = bool(float(row["minimum_margin"]) < RETRY_MARGIN_THRESHOLD)
        pass_frame.at[idx, "fresh_retry_eligible"] = bool((not unlocked) and float(row["minimum_margin"]) < RETRY_MARGIN_THRESHOLD)

    return pass_frame


def analyse_recognition_sessions(recognition_root: Path, result_dir: Path | None = None):
    recognition_root = Path(recognition_root)
    headers = []
    pass_rows = []

    for session in SESSION_IDS:
        session_dir = recognition_root / session
        report_path = session_dir / "AUTO_flow_report.txt"
        if not report_path.exists():
            raise FileNotFoundError(f"Missing frozen RQ23 flow report: {report_path}")
        header, passes = parse_flow_report(report_path)
        if header["session"] != session:
            raise ValueError(f"Session mismatch in {report_path}: {header['session']} != {session}")
        if header["true_code"] is None or len(str(header["true_code"])) != 4:
            raise ValueError(f"Missing four-digit post-hoc true code in {report_path}")
        headers.append(header)
        pass_frame = pd.DataFrame(passes)
        pass_frame = add_exact_candidate_ranks(pass_frame, session_dir)
        pass_rows.extend(pass_frame.to_dict("records"))

    session_df = pd.DataFrame(headers)
    pass_df = pd.DataFrame(pass_rows).sort_values(["session", "pass_index"]).reset_index(drop=True)

    first = pass_df[pass_df["pass_index"] == 1].copy()
    final_pass_index = pass_df.groupby("session")["pass_index"].max().rename("final_pass_index")
    final_rows = pass_df.merge(final_pass_index, on="session")
    final_rows = final_rows[final_rows["pass_index"] == final_rows["final_pass_index"]].copy()

    session_summary = first[[
        "session", "true_code", "start_code", "end_code", "pass_outcome", "minimum_margin",
        "full_prefix_top1_correct", "static_top2_prefix_covered", "static_top3_prefix_covered",
        "physical_unlock", "low_margin", "fresh_retry_eligible",
        "W1_true_rank", "W2_true_rank", "W4_true_rank",
    ]].rename(columns={
        "start_code": "pass1_start_code",
        "end_code": "pass1_end_code",
        "pass_outcome": "pass1_outcome",
        "minimum_margin": "pass1_minimum_margin",
        "physical_unlock": "pass1_physical_unlock",
        "low_margin": "pass1_low_margin",
        "fresh_retry_eligible": "pass1_fresh_retry_eligible",
    })
    final_map = final_rows.set_index("session")
    session_summary["passes_used"] = session_summary["session"].map(final_map["final_pass_index"]).astype(int)
    session_summary["final_physical_unlock"] = session_summary["session"].map(final_map["physical_unlock"]).astype(bool)
    session_summary["final_end_code"] = session_summary["session"].map(final_map["end_code"])
    session_summary["final_code_correct"] = session_summary["final_end_code"].astype(str).eq(session_summary["true_code"].astype(str))

    failures = first[~first["physical_unlock"]].copy()
    eligible = failures[failures["fresh_retry_eligible"]].copy()
    rescued_sessions = set(
        final_rows[(final_rows["physical_unlock"]) & (final_rows["pass_index"] > 1)]["session"].astype(str)
    )

    metrics = pd.DataFrame([
        {"metric": "n_sessions", "value": len(session_summary)},
        {"metric": "first_pass_unlocks", "value": int(session_summary["pass1_physical_unlock"].sum())},
        {"metric": "first_pass_unlock_rate", "value": float(session_summary["pass1_physical_unlock"].mean())},
        {"metric": "final_unlocks", "value": int(session_summary["final_physical_unlock"].sum())},
        {"metric": "final_unlock_rate", "value": float(session_summary["final_physical_unlock"].mean())},
        {"metric": "first_pass_failures", "value": len(failures)},
        {"metric": "low_margin_first_passes", "value": int(session_summary["pass1_low_margin"].sum())},
        {"metric": "fresh_retry_eligible_failures", "value": len(eligible)},
        {"metric": "fresh_retry_rescues", "value": sum(s in rescued_sessions for s in eligible["session"].astype(str))},
        {"metric": "failed_pass_static_top2_coverage", "value": float(failures["static_top2_prefix_covered"].mean()) if len(failures) else np.nan},
        {"metric": "failed_pass_static_top3_coverage", "value": float(failures["static_top3_prefix_covered"].mean()) if len(failures) else np.nan},
    ])

    recovery_rows = []
    for _, row in failures.iterrows():
        session = str(row["session"])
        final = final_map.loc[session]
        recovery_rows.append({
            "session": session,
            "true_code": row["true_code"],
            "pass1_minimum_margin": float(row["minimum_margin"]),
            "W1_true_rank": row["W1_true_rank"],
            "W2_true_rank": row["W2_true_rank"],
            "W4_true_rank": row["W4_true_rank"],
            "static_top2_prefix_covered": bool(row["static_top2_prefix_covered"]),
            "static_top3_prefix_covered": bool(row["static_top3_prefix_covered"]),
            "fresh_retry_eligible": bool(row["fresh_retry_eligible"]),
            "fresh_retry_used": int(final["pass_index"]) > 1,
            "fresh_retry_unlock": bool(final["physical_unlock"] and int(final["pass_index"]) > 1),
            "pass2_start_code": final["start_code"] if int(final["pass_index"]) > 1 else None,
            "pass2_end_code": final["end_code"] if int(final["pass_index"]) > 1 else None,
            "pass2_minimum_margin": float(final["minimum_margin"]) if int(final["pass_index"]) > 1 else np.nan,
        })
    recovery_df = pd.DataFrame(recovery_rows)

    if result_dir is not None:
        result_dir = Path(result_dir)
        result_dir.mkdir(parents=True, exist_ok=True)
        session_summary.to_csv(result_dir / "RQ23_Session_Summary.csv", index=False)
        pass_df.to_csv(result_dir / "RQ23_Pass_Detail.csv", index=False)
        metrics.to_csv(result_dir / "RQ23_Metrics.csv", index=False)
        recovery_df.to_csv(result_dir / "RQ23_Recovery_Cases.csv", index=False)

    return session_summary, pass_df, metrics, recovery_df


def save_figures(session_summary: pd.DataFrame, recovery_df: pd.DataFrame, result_dir: Path):
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    first_rate = 100 * float(session_summary["pass1_physical_unlock"].mean())
    final_rate = 100 * float(session_summary["final_physical_unlock"].mean())
    counts = [
        f"{int(session_summary['pass1_physical_unlock'].sum())}/{len(session_summary)}",
        f"{int(session_summary['final_physical_unlock'].sum())}/{len(session_summary)}",
    ]

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    bars = ax.bar([0, 1], [first_rate, final_rate], width=0.46, color=[LIGHT_BLUE, DARK_BLUE])
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["First recognition pass", "After closed-loop recovery"])
    ax.set_ylabel("Physical unlock success")
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, pos: f"{y:.0f}%"))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.12, zorder=0)
    for bar, value, count in zip(bars, [first_rate, final_rate], counts):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.1f}%\n({count})", ha="center", va="bottom", fontsize=9, color=DARK_GREY)
    fig.tight_layout()
    fig.savefig(result_dir / "RQ23_Fig1_Closed_Loop_Success.png", dpi=300, bbox_inches="tight")
    fig.savefig(result_dir / "RQ23_Fig1_Closed_Loop_Success.pdf", bbox_inches="tight")
    plt.show()

    if len(recovery_df):
        top2 = 100 * float(recovery_df["static_top2_prefix_covered"].mean())
        top3 = 100 * float(recovery_df["static_top3_prefix_covered"].mean())
        retry = 100 * float(recovery_df["fresh_retry_unlock"].mean())
        values = [top2, top3, retry]
        labels = ["Static Top-2\nprefix set", "Static Top-3\nprefix set", "Fresh independent\nretry"]
        colors = [LIGHT_BLUE, LIGHT_BLUE, DARK_BLUE]
        fig, ax = plt.subplots(figsize=(6.8, 4.2))
        bars = ax.bar(np.arange(3), values, width=0.5, color=colors)
        ax.set_xticks(np.arange(3))
        ax.set_xticklabels(labels)
        ax.set_ylabel("Recovery on observed failed pass")
        ax.set_ylim(0, 110)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, pos: f"{y:.0f}%"))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.12, zorder=0)
        n = len(recovery_df)
        for bar, value in zip(bars, values):
            successes = int(round(value / 100 * n))
            ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.0f}%\n({successes}/{n})", ha="center", va="bottom", fontsize=9, color=DARK_GREY)
        fig.tight_layout()
        fig.savefig(result_dir / "RQ23_Fig2_Observed_Recovery_Strategies.png", dpi=300, bbox_inches="tight")
        fig.savefig(result_dir / "RQ23_Fig2_Observed_Recovery_Strategies.pdf", bbox_inches="tight")
        plt.show()


def write_report(session_summary: pd.DataFrame, pass_df: pd.DataFrame, recovery_df: pd.DataFrame, result_dir: Path):
    result_dir = Path(result_dir)
    n = len(session_summary)
    first_n = int(session_summary["pass1_physical_unlock"].sum())
    final_n = int(session_summary["final_physical_unlock"].sum())
    low_n = int(session_summary["pass1_low_margin"].sum())
    failed_n = int((~session_summary["pass1_physical_unlock"]).sum())

    lines = [
        "# RQ23 — Closed-Loop Recovery / Fresh Retry",
        "",
        "## Research question",
        "",
        "Can a fresh independent recognition pass recover a physical failure that static Top-k reuse cannot, and what evidence should trigger that retry?",
        "",
        "## Frozen operational rule",
        "",
        "The deployed recovery logic is sequential rather than margin-only: first attempt the Top-1 prefix and W3 physical sweep; only if no physical unlock occurs and the minimum W1/W2/W4 margin is below 0.20 is a fresh full recognition pass requested from a new visible start state.",
        "",
        "## Operational evidence set",
        "",
        f"Six frozen automatic-recognition sessions with post-hoc ground truth were audited: {', '.join(session_summary['true_code'].astype(str))}.",
        "",
        f"- First-pass physical unlock: {first_n}/{n} ({100*first_n/n:.1f}%).",
        f"- Final physical unlock after the closed-loop procedure: {final_n}/{n} ({100*final_n/n:.1f}%).",
        f"- First passes below the 0.20 margin threshold: {low_n}/{n}.",
        f"- First-pass physical failures: {failed_n}/{n}.",
        "",
        "The low-margin condition is therefore not a standalone failure detector. One successful session (2475) had a minimum first-pass margin of 0.174 but physically opened on that pass. Physical failure remains the primary trigger; margin is secondary evidence used only after failure.",
        "",
        "## Observed recovery case",
        "",
    ]

    if len(recovery_df):
        for _, r in recovery_df.iterrows():
            w2_rank = int(r["W2_true_rank"]) if not pd.isna(r["W2_true_rank"]) else None
            lines.extend([
                f"Session {r['session']} (true code {r['true_code']}) failed on pass 1 with minimum margin {r['pass1_minimum_margin']:.3f}.",
                f"The true upstream ranks were W1={int(r['W1_true_rank']) if not pd.isna(r['W1_true_rank']) else 'unknown'}, W2={w2_rank if w2_rank is not None else '>3'}, W4={int(r['W4_true_rank']) if not pd.isna(r['W4_true_rank']) else 'unknown'}.",
                f"Consequently, the correct W1/W2/W4 prefix was {'inside' if r['static_top2_prefix_covered'] else 'outside'} the static Top-2 Cartesian fallback and {'inside' if r['static_top3_prefix_covered'] else 'outside'} the static Top-3 Cartesian fallback.",
                f"Fresh Retry changed the visible start state to {r['pass2_start_code']} and ended at {r['pass2_end_code']}; physical unlock was {'successful' if r['fresh_retry_unlock'] else 'not successful'}.",
                "",
            ])

    lines.extend([
        "## Interpretation",
        "",
        "The operational evidence supports Fresh Retry as a complementary recovery mechanism rather than a replacement for Top-k search. Static Top-k is inexpensive when the true digits remain inside the original ranking set, but it cannot recover an upstream digit that has fallen outside that set. A fresh reseated observation can change the acoustic/mechanical sample and therefore change the ranking itself.",
        "",
        "The 6924 run is the critical observed example: the true W2 digit was ranked fourth on the failed pass, so even a Top-3 prefix search could not contain the correct prefix. The independent second pass moved W1, W2 and W4 to Top-1 and physically opened the lock.",
        "",
        "## Limitations",
        "",
        "This is an operational audit, not a randomized comparison of recovery policies. Only one of the six frozen sessions required Fresh Retry, so the 1/1 rescue should be treated as a successful case study rather than a population-level success-rate estimate. The sessions also span real deployment changes such as motor hold-torque improvements. No claim is made that Fresh Retry will always outperform Top-k reuse.",
        "",
        "## Decision",
        "",
        "Retain a hierarchical recovery policy: Top-1 physical attempt first; if the lock remains closed, use confidence to decide whether the current ranking is trustworthy. Static Top-k remains available when the original ranking is plausible, while low-confidence physical failure justifies a fresh independent recognition pass. Physical unlock confirmation remains the final success criterion.",
    ])

    report_path = result_dir / "RQ23_Report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    conclusion = {
        "research_question": "Can a fresh independent recognition pass recover a physical failure that static Top-k reuse cannot, and what evidence should trigger that retry?",
        "sessions": SESSION_IDS,
        "n_sessions": n,
        "first_pass_unlocks": first_n,
        "final_unlocks": final_n,
        "retry_margin_threshold": RETRY_MARGIN_THRESHOLD,
        "low_margin_first_passes": low_n,
        "first_pass_failures": failed_n,
        "observed_recovery_cases": recovery_df.to_dict("records"),
        "conclusion": "Fresh Retry is retained as a complementary recovery path after physical failure plus low confidence. Static Top-k cannot recover digits that fall outside the original candidate set; the 6924 case was rescued only after a fresh independent recognition changed the ranking.",
        "limitation": "Only one frozen session required Fresh Retry; this is operational case-study evidence, not a randomized policy comparison.",
    }
    (result_dir / "RQ23_conclusion.json").write_text(json.dumps(conclusion, indent=2, default=str), encoding="utf-8")

    run_info = {
        "rq": "RQ23",
        "analysis_type": "frozen closed-loop operational audit",
        "source_root": "dataset/recognition_results",
        "session_ids": SESSION_IDS,
        "main_model": "MAIN v8 deployed engineering model",
        "retry_rule": "physical failure AND min wheel margin < 0.20 -> fresh full recognition from a new visible start state",
        "static_top2_hypotheses": 8,
        "static_top3_hypotheses": 27,
        "success_criterion": "physical unlock confirmation",
    }
    (result_dir / "RQ23_run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    return report_path
