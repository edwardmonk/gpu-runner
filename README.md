# gpu-runner

Generic on-demand GPU job runner. Launches a cloud instance, uploads inputs, runs a script, downloads outputs, and terminates — always, even on failure.

## Usage

```bash
pip install -r requirements.txt
LAMBDA_API_KEY=your_key python runner.py examples/vision.yaml
python runner.py examples/vision.yaml --dry-run
```

## Job manifest

```yaml
provider: lambda          # lambda | (aws, runpod — future)
instance_type: gpu_1x_a10
ssh_key: ~/.ssh/lambda    # path to private key
ssh_key_name: my-key      # key name registered with provider
region: us-east-1         # optional — auto-selects if omitted

inputs:
  - local: /path/to/file
    remote: ~/file

script: |
  pip install something
  python job.py --input file --output result.csv

outputs:
  - remote: ~/result.csv
    local: /path/to/result.csv
```

## Adding a provider

Add a class to `providers/` implementing `launch`, `wait_for_ip`, `get_ip`, and `terminate`, then register it in `providers/__init__.py`.
