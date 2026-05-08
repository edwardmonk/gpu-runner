#!/usr/bin/env python3
"""
runner.py — generic GPU-on-demand job runner

Launches a cloud GPU instance, uploads inputs, runs a script,
downloads outputs, and terminates. Always terminates in a finally
block so a failed job never leaves a billable instance running.

Usage:
    python runner.py examples/vision.yaml
    python runner.py examples/vision.yaml --dry-run

Environment variables:
    LAMBDA_API_KEY      API key for Lambda Labs
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from providers import PROVIDERS


# ---------------------------------------------------------------------------
# SSH / SCP helpers
# ---------------------------------------------------------------------------

def _ssh_args(ip: str, key: str) -> list[str]:
    return [
        "-i", os.path.expanduser(key),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
    ]


def ssh_run(ip: str, key: str, command: str, timeout: int = 86400) -> int:
    return subprocess.run(
        ["ssh", *_ssh_args(ip, key), f"ubuntu@{ip}", command],
        timeout=timeout,
    ).returncode


def wait_for_ssh(ip: str, key: str, retries: int = 24, interval: int = 15) -> bool:
    for attempt in range(retries):
        try:
            if ssh_run(ip, key, "echo ok", timeout=15) == 0:
                return True
        except Exception:
            pass
        print(f"  waiting for SSH ({attempt + 1}/{retries})...")
        time.sleep(interval)
    return False


def scp_up(local: str, ip: str, key: str, remote: str):
    subprocess.run(
        ["scp", *_ssh_args(ip, key), local, f"ubuntu@{ip}:{remote}"],
        check=True,
    )


def scp_down(ip: str, key: str, remote: str, local: str):
    subprocess.run(
        ["scp", *_ssh_args(ip, key), f"ubuntu@{ip}:{remote}", local],
        check=True,
    )


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------

def run_job(manifest: dict, dry_run: bool = False):
    provider_name = manifest.get("provider", "lambda")
    instance_type = manifest["instance_type"]
    ssh_key = manifest["ssh_key"]
    ssh_key_name = manifest["ssh_key_name"]
    region = manifest.get("region")
    script = manifest["script"].strip()
    inputs = manifest.get("inputs", [])
    outputs = manifest.get("outputs", [])

    api_key_var = f"{provider_name.upper()}_API_KEY"
    api_key = os.environ.get(api_key_var)
    if not api_key:
        print(f"Error: set {api_key_var} environment variable", file=sys.stderr)
        sys.exit(1)

    if provider_name not in PROVIDERS:
        print(f"Error: unknown provider '{provider_name}'. Available: {list(PROVIDERS)}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"[dry-run] provider:       {provider_name}")
        print(f"[dry-run] instance_type:  {instance_type}")
        print(f"[dry-run] ssh_key:        {ssh_key}")
        print(f"[dry-run] inputs:         {[i['local'] for i in inputs]}")
        print(f"[dry-run] outputs:        {[o['local'] for o in outputs]}")
        print(f"[dry-run] script:\n{script}")
        return

    provider = PROVIDERS[provider_name](api_key)
    instance_id = None

    try:
        print(f"Launching {instance_type} on {provider_name}...")
        instance_id = provider.launch(instance_type, ssh_key_name, region)
        print(f"  instance ID: {instance_id}")

        print("Waiting for IP address...")
        ip = provider.wait_for_ip(instance_id)
        print(f"  IP: {ip}")

        print("Waiting for SSH to become available...")
        if not wait_for_ssh(ip, ssh_key):
            raise RuntimeError("SSH never became available — check instance and security settings")
        print("  SSH ready")

        for item in inputs:
            print(f"Uploading {item['local']} → {item['remote']}")
            scp_up(item["local"], ip, ssh_key, item["remote"])

        # Write script to a temp file, upload, execute
        print("Running job script...")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/usr/bin/env bash\nset -euo pipefail\n\n")
            f.write(script)
            tmp_script = f.name
        try:
            scp_up(tmp_script, ip, ssh_key, "~/job_script.sh")
        finally:
            os.unlink(tmp_script)

        rc = ssh_run(ip, ssh_key, "bash ~/job_script.sh")
        if rc != 0:
            raise RuntimeError(f"Job script exited with code {rc}")
        print("  Job complete")

        for item in outputs:
            print(f"Downloading {item['remote']} → {item['local']}")
            scp_down(ip, ssh_key, item["remote"], item["local"])

        print("All outputs collected.")

    finally:
        if instance_id:
            print(f"Terminating instance {instance_id}...")
            try:
                provider.terminate(instance_id)
                print("  Terminated.")
            except Exception as e:
                print(f"\n*** WARNING: termination failed: {e}")
                print(f"*** MANUAL ACTION REQUIRED: terminate {instance_id} on {provider_name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run a job on an on-demand GPU instance and collect output."
    )
    parser.add_argument("manifest", help="Path to job YAML manifest")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without launching anything")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    run_job(manifest, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
