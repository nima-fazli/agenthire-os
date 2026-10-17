"""Small real HTTP/PDF/two-worker/index workflow gate for isolated CI."""

from scripts.workload_benchmark import main as benchmark


def main():
    return benchmark(["--execute", "--items", "2", "--concurrency", "2"])


if __name__ == "__main__":
    raise SystemExit(main())
