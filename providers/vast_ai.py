import time
import requests


class VastProvider:
    """
    Vast.ai provider. Uses the interruptible (spot) market by default for lowest cost.

    instance_type in the manifest is a GPU name filter, e.g. "RTX_3090" or "RTX_4090".
    Vast searches available offers matching that GPU and picks the cheapest.

    ssh_key_name is not used — Vast injects keys via the API key account's registered keys.
    Set your public key at https://vast.ai/console/account/

    Environment variable: VAST_API_KEY
    """

    BASE = "https://console.vast.ai/api/v0"
    # Docker image with CUDA + PyTorch pre-installed
    DEFAULT_IMAGE = "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _search_offers(self, gpu_name: str, interruptible: bool = True) -> list[dict]:
        instance_type = "interruptible" if interruptible else "on-demand"
        params = {
            "q": (
                f'{{"rentable":{{"eq":true}},"num_gpus":{{"eq":1}},'
                f'"gpu_name":{{"eq":"{gpu_name}"}},'
                f'"type":"{instance_type}"}}'
            ),
            "order": "dph_total asc",
            "limit": 20,
        }
        r = requests.get(f"{self.BASE}/bundles/", headers=self.headers, params=params)
        r.raise_for_status()
        return r.json().get("offers", [])

    def launch(self, instance_type: str, ssh_key_name: str | None = None, region: str | None = None) -> str:
        offers = self._search_offers(instance_type, interruptible=True)
        if not offers:
            # Fall back to on-demand if no interruptible capacity
            offers = self._search_offers(instance_type, interruptible=False)
        if not offers:
            raise RuntimeError(f"No Vast.ai offers available for GPU: {instance_type}")

        offer = offers[0]
        offer_id = offer["id"]
        price = offer.get("dph_total", "?")
        print(f"  best offer: {offer.get('gpu_name')} ${price:.3f}/hr (id: {offer_id})")

        r = requests.put(
            f"{self.BASE}/asks/{offer_id}/",
            headers=self.headers,
            json={
                "client_id": "me",
                "image": self.DEFAULT_IMAGE,
                "runtype": "ssh",
                "disk": 20,
            },
        )
        r.raise_for_status()
        data = r.json()
        instance_id = str(data.get("new_contract") or data.get("id"))
        return instance_id

    def _get_instance(self, instance_id: str) -> dict | None:
        r = requests.get(f"{self.BASE}/instances/{instance_id}/", headers=self.headers)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        instances = r.json().get("instances", [])
        return instances[0] if instances else None

    def wait_for_connection(self, instance_id: str, timeout: int = 300) -> tuple[str, int, str]:
        """Returns (ip, port, user). Vast.ai uses non-standard SSH ports."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            inst = self._get_instance(instance_id)
            if inst and inst.get("actual_status") == "running":
                ip = inst.get("ssh_host") or inst.get("public_ipaddr")
                port = inst.get("ssh_port", 22)
                if ip and port:
                    return ip, int(port), "root"
            time.sleep(10)
        raise TimeoutError(f"Instance {instance_id} did not become ready within {timeout}s")

    def terminate(self, instance_id: str):
        r = requests.delete(f"{self.BASE}/instances/{instance_id}/", headers=self.headers)
        r.raise_for_status()
