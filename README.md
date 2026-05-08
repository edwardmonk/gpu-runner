# gpu-runner

A lightweight pattern for on-demand GPU compute. An orchestration server launches a cloud GPU instance, uploads inputs, runs a job script, retrieves outputs, and terminates — always, even on failure.

## The pattern

Any server (development, production, VPS, local machine) can act as the orchestrator. It does not need GPU hardware. The GPU instance is ephemeral — it exists only for the duration of the job.

```text
Orchestration server                  Cloud GPU instance
        │                                      │
        ├── 1. launch via provider API ───────►│  (booting)
        │                                      │
        ├── 2. wait for SSH ──────────────────►│  (ready)
        │                                      │
        ├── 3. upload inputs via SCP ─────────►│
        │                                      │
        │                                      │  (job runs)
        │                                      │
        ◄── 4. download outputs via SCP ────────┤
        │                                      │
        └── 5. terminate via provider API ─────►│  (gone)
```

This works for any compute-intensive batch job: embedding generation, LLM inference, image captioning, fine-tuning, data processing. The provider and job are independently configurable.

## Requirements

```bash
pip install -r requirements.txt
```

The orchestration server needs:

- Python 3.10+
- `requests`, `pyyaml`
- SSH access to the GPU instance (private key on the orchestration server)
- Provider API key set as an environment variable

## Usage

```bash
# Dry run — prints plan, launches nothing
python runner.py examples/test.yaml --dry-run

# Real run
LAMBDA_API_KEY=your_key python runner.py examples/vision.yaml
```

On a server where the API key is already in the environment:

```bash
python runner.py examples/vision.yaml
```

## Job manifest

Each job is defined by a YAML file:

```yaml
provider: lambda              # which cloud provider to use
instance_type: gpu_1x_a10    # instance type (provider-specific)
ssh_key: ~/.ssh/lambda        # path to SSH private key on orchestration server
ssh_key_name: my-key-name     # key name as registered with the provider

region: us-east-1             # optional — auto-selects available region if omitted

inputs:
  - local: /path/on/orchestrator
    remote: ~/path/on/instance

script: |
  # Shell script that runs on the GPU instance
  pip install -r requirements.txt -q
  python job.py --input data.csv --output results.csv

outputs:
  - remote: ~/results.csv
    local: /path/on/orchestrator/results.csv
```

The script runs as `ubuntu` on the GPU instance inside `bash -euo pipefail` — any error stops execution and triggers termination.

## Environment variables

| Variable       | Provider    | Description                                   |
| -------------- | ----------- | --------------------------------------------- |
| LAMBDA_API_KEY | Lambda Labs | API key from lambda.ai/cloud → API Keys       |

## Providers

### Lambda Labs (`provider: lambda`)

Supports all Lambda instance types. Instance type names: `gpu_1x_a10`, `gpu_1x_h100_pcie`, `gpu_1x_h100_sxm5`, etc. Check available capacity:

```python
import requests, os

r = requests.get(
    "https://cloud.lambdalabs.com/api/v1/instance-types",
    headers={"Authorization": f"Bearer {os.environ['LAMBDA_API_KEY']}"}
)
for name, info in r.json()["data"].items():
    if info["regions_with_capacity_available"]:
        price = info["instance_type"]["price_cents_per_hour"]
        print(f"{name}  ${price/100:.2f}/hr")
```

### Adding a provider

Create `providers/your_provider.py` implementing:

```python
class YourProvider:
    def __init__(self, api_key: str): ...
    def launch(self, instance_type: str, ssh_key_name: str, region: str | None) -> str:
        """Launch instance, return instance_id."""
    def wait_for_ip(self, instance_id: str, timeout: int) -> str:
        """Poll until IP is assigned, return IP."""
    def get_ip(self, instance_id: str) -> str | None:
        """Return current IP or None if not ready."""
    def terminate(self, instance_id: str):
        """Terminate the instance."""
```

Register it in `providers/__init__.py`:

```python
from .your_provider import YourProvider

PROVIDERS = {
    "lambda": LambdaProvider,
    "your_provider": YourProvider,
}
```

Then use `provider: your_provider` in any manifest.

## Cost model

Cost = (instance $/hr) × (wall-clock hours from launch to termination).

The runner terminates in a `finally` block so a crashed job does not leave a running instance. If termination itself fails, a warning is printed with the instance ID for manual cleanup.

Approximate costs on Lambda Labs (May 2026):

| Instance            | GPU        | $/hr  | 10k images | 50k images |
| ------------------- | ---------- | ----- | ---------- | ---------- |
| `gpu_1x_a10`        | A10 24GB   | $1.29 | ~$10       | ~$50       |
| `gpu_1x_h100_pcie`  | H100 80GB  | $3.29 | ~$3        | ~$15       |
| `gpu_1x_h100_sxm5`  | H100 80GB  | $4.29 | ~$2        | ~$10       |

Faster GPUs cost more per hour but finish sooner — for large jobs H100 is often cheaper overall.

## Examples

| Manifest              | Description                                           |
| --------------------- | ----------------------------------------------------- |
| `examples/test.yaml`  | GPU smoke test — prints device info, runs matmul      |
| `examples/vision.yaml`| LinkedCulture image captioning via Qwen2.5-VL         |
