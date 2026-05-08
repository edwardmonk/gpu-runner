import time
import requests


class LambdaProvider:
    BASE = "https://cloud.lambdalabs.com/api/v1"

    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def launch(self, instance_type: str, ssh_key_name: str, region: str | None = None) -> str:
        if not region:
            region = self._find_region(instance_type)
        r = requests.post(f"{self.BASE}/instances", headers=self.headers, json={
            "instance_type_name": instance_type,
            "region_name": region,
            "ssh_key_names": [ssh_key_name],
            "quantity": 1,
        })
        r.raise_for_status()
        return r.json()["data"]["instance_ids"][0]

    def _find_region(self, instance_type: str) -> str:
        r = requests.get(f"{self.BASE}/instance-types", headers=self.headers)
        r.raise_for_status()
        types = r.json()["data"]
        if instance_type in types:
            regions = types[instance_type].get("regions_with_capacity_available", [])
            if regions:
                return regions[0]["name"]
        raise RuntimeError(f"No region with capacity available for {instance_type}")

    def get_ip(self, instance_id: str) -> str | None:
        r = requests.get(f"{self.BASE}/instances/{instance_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()["data"].get("ip")

    def wait_for_ip(self, instance_id: str, timeout: int = 300) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ip = self.get_ip(instance_id)
            if ip:
                return ip
            time.sleep(10)
        raise TimeoutError(f"Instance {instance_id} did not get an IP within {timeout}s")

    def terminate(self, instance_id: str):
        requests.delete(
            f"{self.BASE}/instances",
            headers=self.headers,
            json={"instance_ids": [instance_id]},
        ).raise_for_status()
