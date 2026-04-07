import socket
import sys


def resolve_host(hostname):
    # Translate a hostname into IP addresses to verify DNS reachability.
    return [info[4][0] for info in socket.getaddrinfo(hostname, None)]


def test_tcp_connection(host, port):
    # Attempt a TCP handshake to ensure the endpoint is reachable from this network.
    sock = socket.create_connection((host, port), timeout=6)
    sock.close()


def main():
    endpoints = [
        ("engage.cloudflareclient.com", 2408),
        ("api.anthropic.com", 443),
        ("www.cloudflare.com", 443),
    ]
    failures = []
    for host, port in endpoints:
        try:
            ips = resolve_host(host)
            print(f"{host} resolved to {ips}")
            test_tcp_connection(host, port)
            print(f"{host}:{port} is reachable")
        except Exception as exc:
            print(f"ERROR: {host}:{port} -> {exc}")
            failures.append((host, port, exc))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
