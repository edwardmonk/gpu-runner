import time
import requests


class VastProvider:
    """
    Vast.ai provider. Picks the cheapest available single-GPU offer matching
    the requested GPU name. If instance_type is omitted or 'cheapest', picks
    the cheapest available offer regardless of GPU type.

    ssh_key_name is not used — Vast injects keys registered in your account.
    Register your public key at https://vast.ai/console/account/

    Environment variable: VAST_API_KEY
    """

    BASE = "https://console.vast.ai/api/v0"
    DEFAULT_IMAGE = "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _available_offers(self, gpu_filter: str | None = None, num_gpus: int = 1) -> list[dict]:
        r = requests.get(f"{self.BASE}/bundles/", headers=self.headers)
        r.raise_for_status()
        offers = r.json().get("offers", [])

        available = [
            o for o in offers
            if o.get("rentable")
            and not o.get("rented")
            and o.get("dph_total")
            and o.get("num_gpus", 0) == num_gpus
            and (o.get("reliability2") or o.get("reliability") or 0) >= 0.90
        ]

        if gpu_filter and gpu_filter.lower() not in ("cheapest", "any"):
            normalized = gpu_filter.replace("_", " ").lower()
            available = [
                o for o in available
                if normalized in (o.get("gpu_name") or "").lower()
            ]

        available.sort(key=lambda o: o["dph_total"])
        return available

    def launch(self, instance_type: str, ssh_key_name: str | None = None, region: str | None = None) -> str:
        for attempt in range(5):
            offers = self._available_offers(gpu_filter=instance_type)
            if not offers:
                raise RuntimeError(
                    f"No Vast.ai offers available for '{instance_type}'. "
                    f"Check https://vast.ai/console/search/ for current availability."
                )

            offer = offers[0]
            offer_id = offer["id"]
            print(f"  trying: {offer.get('gpu_name')} ${offer['dph_total']:.3f}/hr (id: {offer_id})")

            r = requests.put(
                f"{self.BASE}/asks/{offer_id}/",
                headers=self.headers,
                json={
                    "client_id": "me",
                    "image": self.DEFAULT_IMAGE,
                    "runtype": "ssh",
                    "disk": 40,
                },
            )
            if r.status_code == 200:
                data = r.json()
                instance_id = str(data.get("new_contract") or data.get("id"))
                print(f"  launched: {instance_id}")
                return instance_id
            print(f"  offer taken (attempt {attempt + 1}/5), retrying...")
            time.sleep(2)

        raise RuntimeError("Failed to launch after 5 attempts — all offers taken. Try again.")

    def _get_instance(self, instance_id: str) -> dict | None:
        r = requests.get(f"{self.BASE}/instances/", headers=self.headers)
        r.raise_for_status()
        instances = r.json().get("instances") or []
        if isinstance(instances, dict):
            instances = list(instances.values())
        for inst in instances:
            if str(inst.get("id")) == str(instance_id):
                return inst
        return None

    def wait_for_connection(self, instance_id: str, timeout: int = 600) -> tuple[str, int, str]:
        """Returns (ip, port, user). Vast.ai uses non-standard SSH ports."""
        deadline = time.time() + timeout
        last_status = None
        while time.time() < deadline:
            inst = self._get_instance(instance_id)
            if inst:
                status = inst.get("actual_status") or inst.get("status_msg") or "unknown"
                if status != last_status:
                    print(f"  instance status: {status}")
                    last_status = status
                if status == "running":
                    ip = inst.get("ssh_host") or inst.get("public_ipaddr")
                    port = inst.get("ssh_port", 22)
                    if ip and port:
                        return ip, int(port), "root"
            time.sleep(10)
        raise TimeoutError(f"Instance {instance_id} did not become ready within {timeout}s")

    def terminate(self, instance_id: str):
        r = requests.delete(f"{self.BASE}/instances/{instance_id}/", headers=self.headers)
        r.raise_for_status()
