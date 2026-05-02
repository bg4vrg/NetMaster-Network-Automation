import json
import sys

from switch_driver import H3CManager, HuaweiManager


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    sw = payload["switch"]
    vendor = str(sw.get("vendor") or "h3c").lower()
    manager_cls = HuaweiManager if vendor == "huawei" else H3CManager
    manager = manager_cls(
        sw["ip"],
        sw.get("username") or "",
        sw.get("password") or "",
        int(sw.get("port") or 22),
    )
    bindings = manager.get_all_bindings()
    print(json.dumps({"status": "success", "bindings": bindings}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
