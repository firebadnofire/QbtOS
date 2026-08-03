#!/usr/bin/env python3
"""Create deterministic qbtOS release and moving-feed JSON documents."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def release_manifest(args):
    bundle = Path(args.bundle)
    image = Path(args.image)
    return {
        "schema": 1,
        "version": args.version,
        "build_date": args.build_date,
        "revision": args.revision,
        "source_tag": args.source_tag,
        "commit": args.commit,
        "compatible": "qbtos-rpi4",
        "channel": "stable",
        "bundle_filename": bundle.name,
        "image_filename": image.name,
        "checksum_filename": f"{args.version}.sha256",
        "bundle_sha256": sha256(bundle),
        "image_sha256": sha256(image),
        "bundle_size": bundle.stat().st_size,
        "image_size": image.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-date", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url")
    args = parser.parse_args()

    document = release_manifest(args)
    if args.base_url:
        base = args.base_url.rstrip("/") + "/"
        document["bundle_url"] = urljoin(base, document["bundle_filename"])
        document["image_url"] = urljoin(base, document["image_filename"])
        document["checksum_url"] = urljoin(base, document["checksum_filename"])

    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    Path(args.output).write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
