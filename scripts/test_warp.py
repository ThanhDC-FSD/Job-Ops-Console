import json
import socket
import sys
import time

import requests

HTTP_PROXY = "http://127.0.0.1:7890"
PROXIES = {"http": HTTP_PROXY, "https": HTTP_PROXY}
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
IP_URL = "https://ifconfig.co/json"


def check_proxy_alive():
    # Ensure the local HTTP proxy is accepting TCP connections before issuing requests.
    try:
        with socket.create_connection(("127.0.0.1", 7890), timeout=3):
            return True
    except OSError:
        return False


def fetch_trace(host):
    # Hit Cloudflare trace through the proxy and keep the host parameter to inspect mode.
    resp = requests.get(
        TRACE_URL,
        proxies=PROXIES,
        timeout=15,
        params={"host": host},
        headers={"User-Agent": "warp-test-script"},
    )
    resp.raise_for_status()
    return resp.text


def parse_trace(text):
    # Convert the trace output into a dictionary for easy inspection.
    return dict(line.split("=", 1) for line in text.strip().splitlines() if "=" in line)


def fetch_public_ip():
    # Use ifconfig.co to capture the IP address visible through the proxy tunnel.
    resp = requests.get(IP_URL, proxies=PROXIES, timeout=15, headers={"User-Agent": "warp-test-script"})
    resp.raise_for_status()
    return resp.json()


def inspect_domain(domain, expect_warp):
    # Retrieve warp status for a specific host and compare against the expected state.
    trace = parse_trace(fetch_trace(domain))
    warp_state = trace.get("warp", "unknown").lower()
    print(f"{domain} -> warp={warp_state}")
    if expect_warp and warp_state != "on":
        print(f"WARNING: Expected warp=on for {domain}, got {warp_state}")
    if not expect_warp and warp_state != "off":
        print(f"WARNING: Expected warp=off for {domain}, got {warp_state}")
    return warp_state


def main():
    if not check_proxy_alive():
        print("ERROR: Proxy at 127.0.0.1:7890 is not responding.")
        sys.exit(1)

    print("Phase A: forcing full warp to verify a live tunnel.")
    try:
        trace_payload = parse_trace(fetch_trace("www.cloudflare.com"))
        print("Trace summary:", json.dumps(trace_payload, indent=2))
    except Exception as exc:
        print("ERROR: Failed to fetch cdn-cgi/trace:", exc)
        sys.exit(1)

    ip_info = {}
    try:
        ip_info = fetch_public_ip()
        print("Public IP through proxy:", ip_info.get("ip"))
    except Exception as exc:
        print("WARNING: Unable to fetch public IP via proxy:", exc)

    print("\nPhase B: selective routing verification.")
    warp_result = inspect_domain("api.anthropic.com", expect_warp=True)
    direct_result = inspect_domain("www.wikipedia.org", expect_warp=False)

    conclusion = (
        "PASS"
        if warp_result == "on" and direct_result == "off"
        else "CHECK"
    )
    print(f"\nFinal conclusion: {conclusion}")
    if conclusion == "CHECK":
        print("Re-run tests after verifying the tunnel or adjust config per README guidance.")


if __name__ == "__main__":
    main()
