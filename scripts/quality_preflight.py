"""Run the repository's shared local and CI quality gates."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_COVERAGE_FILES = ",".join(
    (
        "src/alert_budget.py",
        "src/alert_caption.py",
        "src/alert_contract.py",
        "src/alert_lifecycle.py",
        "src/material_change.py",
        "src/alert_card_renderer.py",
        "src/telegram_client.py",
        "src/deep_link_router.py",
        "src/artifact_contract.py",
        "src/release_manifest.py",
        "src/release_gate.py",
        "src/system_dry_run.py",
    )
)


def _workflow_files() -> list[str]:
    paths = sorted((*ROOT.joinpath(".github", "workflows").glob("*.yml"), *ROOT.joinpath(".github", "workflows").glob("*.yaml")))
    if not paths:
        raise RuntimeError("No GitHub Actions workflow files were found.")
    return [path.relative_to(ROOT).as_posix() for path in paths]


def _changed_test_files(base_sha: str | None) -> list[str]:
    if not base_sha:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    candidates = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip().replace("\\", "/").startswith("tests/")
        and line.strip().replace("\\", "/").endswith(".py")
        and (ROOT / line.strip()).is_file()
    }
    return sorted(candidates)


def static_commands() -> list[tuple[str, list[str]]]:
    workflows = _workflow_files()
    actionlint = shutil.which("actionlint")
    actionlint_command: list[str]
    if actionlint:
        version = subprocess.run([actionlint, "-version"], cwd=ROOT, check=False, capture_output=True, text=True)
        if version.returncode == 0 and "1.7.7" in f"{version.stdout}\n{version.stderr}":
            actionlint_command = [actionlint, *workflows]
        else:
            actionlint_command = [
                "docker",
                "run",
                "--rm",
                "-w",
                "/repo",
                "-v",
                f"{ROOT.as_posix()}:/repo",
                "rhysd/actionlint:1.7.7",
                *workflows,
            ]
    else:
        actionlint_command = [
            "docker",
            "run",
            "--rm",
            "-w",
            "/repo",
            "-v",
            f"{ROOT.as_posix()}:/repo",
            "rhysd/actionlint:1.7.7",
            *workflows,
        ]
    return [
        ("GitHub Actions workflow syntax", actionlint_command),
        ("Ruff source, tests, and quality tooling", ["uv", "run", "ruff", "check", "src", "tests", "scripts"]),
        (
            "Mypy source and quality tooling",
            ["uv", "run", "mypy", "src", "scripts/quality_preflight.py", "scripts/inspect_quality_run.py"],
        ),
    ]


def test_commands(base_sha: str | None) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = [("Reset coverage data", ["uv", "run", "coverage", "erase"])]
    changed_tests = _changed_test_files(base_sha)
    if changed_tests:
        commands.append(("Changed tests", ["uv", "run", "pytest", "-q", "--no-cov", *changed_tests]))
    commands.extend(
        (
            (
                "Full unit suite and project coverage gate",
                [
                    "uv",
                    "run",
                    "pytest",
                    "-q",
                    "--cov=src",
                    "--cov-report=term-missing",
                    "--cov-report=xml",
                    "--cov-fail-under=80",
                ],
            ),
            (
                "Core release and delivery coverage gate",
                [
                    "uv",
                    "run",
                    "coverage",
                    "report",
                    f"--include={CORE_COVERAGE_FILES}",
                    "--fail-under=90",
                ],
            ),
        )
    )
    return commands


def _write_failed_gate(label: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"failed_gate={label}\n")


def run_commands(commands: Sequence[tuple[str, list[str]]], runner=subprocess.run) -> int:
    for label, command in commands:
        print(f"\n==> {label}", flush=True)
        try:
            completed = runner(command, cwd=ROOT, check=False)
        except OSError as exc:
            _write_failed_gate(label)
            print(f"FAILED: {label} could not start ({type(exc).__name__})", file=sys.stderr, flush=True)
            return 127
        if completed.returncode:
            _write_failed_gate(label)
            print(f"FAILED: {label} (exit {completed.returncode})", file=sys.stderr, flush=True)
            return completed.returncode
    _write_failed_gate("none")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    phases = parser.add_mutually_exclusive_group()
    phases.add_argument("--static", action="store_true", help="run workflow syntax, Ruff, and Mypy")
    phases.add_argument("--tests", action="store_true", help="run changed tests and the full test/coverage gates")
    parser.add_argument(
        "--base-sha",
        default=os.environ.get("QUALITY_PREFLIGHT_BASE_SHA") or None,
        help="base commit used to select changed test files; the full suite always runs",
    )
    args = parser.parse_args(argv)
    try:
        if args.static:
            commands = static_commands()
        elif args.tests:
            commands = test_commands(args.base_sha)
        else:
            commands = [*static_commands(), *test_commands(args.base_sha)]
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAILED: could not prepare quality preflight ({type(exc).__name__})", file=sys.stderr)
        return 2
    return run_commands(commands)


if __name__ == "__main__":
    raise SystemExit(main())
