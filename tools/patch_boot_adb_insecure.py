#!/usr/bin/env python3
"""Create a temporary Magisk boot image with ADB host auth disabled.

This is a recovery aid for the rooted GridFront Oukitel tablet when kiosk mode
prevents accepting the normal ADB authorization prompt. It keeps the Android
boot image layout intact and only changes same-length properties in the ramdisk:

    ro.adb.secure=1 -> ro.adb.secure=0
    ro.debuggable=0 -> ro.debuggable=1

The output should be flashed only long enough to install a Scout build that can
append the laptop key to /data/misc/adb/adb_keys, then replaced with the normal
Magisk boot image again.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import struct
from dataclasses import dataclass
from pathlib import Path


BOOT_MAGIC = b"ANDROID!"
CPIO_NEWC_MAGIC = b"070701"


@dataclass(frozen=True)
class BootInfo:
    kernel_size: int
    ramdisk_size: int
    second_size: int
    page_size: int
    ramdisk_offset: int


def align(value: int, page_size: int) -> int:
    return (value + page_size - 1) // page_size * page_size


def parse_boot_info(image: bytes) -> BootInfo:
    if image[:8] != BOOT_MAGIC:
        raise ValueError("not an Android boot image: missing ANDROID! magic")

    kernel_size = struct.unpack_from("<I", image, 8)[0]
    ramdisk_size = struct.unpack_from("<I", image, 16)[0]
    second_size = struct.unpack_from("<I", image, 24)[0]
    page_size = struct.unpack_from("<I", image, 36)[0]
    if page_size <= 0 or page_size > 65536:
        raise ValueError(f"unexpected boot image page size: {page_size}")

    ramdisk_offset = page_size + align(kernel_size, page_size)
    end = ramdisk_offset + ramdisk_size
    if end > len(image):
        raise ValueError("ramdisk extends past end of boot image")

    return BootInfo(
        kernel_size=kernel_size,
        ramdisk_size=ramdisk_size,
        second_size=second_size,
        page_size=page_size,
        ramdisk_offset=ramdisk_offset,
    )


def cpio_field(entry: bytes, offset: int) -> int:
    return int(entry[offset : offset + 8], 16)


def replace_prop_default(cpio: bytes) -> bytes:
    data = bytearray(cpio)
    pos = 0

    while pos + 110 <= len(data):
        header = bytes(data[pos : pos + 110])
        if header[:6] != CPIO_NEWC_MAGIC:
            raise ValueError(f"invalid cpio newc header at offset {pos}")

        namesize = cpio_field(header, 94)
        filesize = cpio_field(header, 54)
        name_start = pos + 110
        name_end = name_start + namesize
        if name_end > len(data):
            raise ValueError("cpio entry name extends past archive")

        raw_name = bytes(data[name_start:name_end])
        name = raw_name.rstrip(b"\0").decode("utf-8", errors="replace")
        file_start = align(name_end, 4)
        file_end = file_start + filesize
        if file_end > len(data):
            raise ValueError(f"cpio entry {name!r} extends past archive")

        if name == "prop.default":
            original = bytes(data[file_start:file_end])
            patched = original
            replacements = {
                b"ro.adb.secure=1": b"ro.adb.secure=0",
                b"ro.debuggable=0": b"ro.debuggable=1",
            }
            for old, new in replacements.items():
                if old not in patched:
                    raise ValueError(f"prop.default did not contain {old.decode()}")
                patched = patched.replace(old, new, 1)

            if len(patched) != len(original):
                raise AssertionError("property patch changed prop.default length")
            data[file_start:file_end] = patched
            return bytes(data)

        pos = align(file_end, 4)
        if name == "TRAILER!!!":
            break

    raise ValueError("prop.default not found in ramdisk cpio")


def gzip_payload(payload: bytes) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as gz:
        gz.write(payload)
    return out.getvalue()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_boot(input_path: Path, output_path: Path) -> BootInfo:
    image = bytearray(input_path.read_bytes())
    info = parse_boot_info(image)

    ramdisk_start = info.ramdisk_offset
    ramdisk_end = ramdisk_start + info.ramdisk_size
    ramdisk_blob = bytes(image[ramdisk_start:ramdisk_end]).rstrip(b"\0")
    cpio = gzip.decompress(ramdisk_blob)
    patched_cpio = replace_prop_default(cpio)
    patched_ramdisk = gzip_payload(patched_cpio)

    if len(patched_ramdisk) > info.ramdisk_size:
        raise ValueError(
            f"patched ramdisk is larger than original field "
            f"({len(patched_ramdisk)} > {info.ramdisk_size})"
        )

    image[ramdisk_start:ramdisk_end] = patched_ramdisk.ljust(info.ramdisk_size, b"\0")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    return info


def verify_output(output_path: Path) -> None:
    image = output_path.read_bytes()
    info = parse_boot_info(image)
    ramdisk = bytes(
        image[info.ramdisk_offset : info.ramdisk_offset + info.ramdisk_size]
    ).rstrip(b"\0")
    cpio = gzip.decompress(ramdisk)
    if b"ro.adb.secure=0" not in cpio:
        raise ValueError("verification failed: ro.adb.secure=0 missing")
    if b"ro.debuggable=1" not in cpio:
        raise ValueError("verification failed: ro.debuggable=1 missing")
    if b"ro.adb.secure=1" in cpio:
        raise ValueError("verification failed: ro.adb.secure=1 still present")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=r"C:\Users\helve\magisk_patched_boot_b.img",
        type=Path,
        help="source Magisk boot image",
    )
    parser.add_argument(
        "--output",
        default=r"C:\Users\helve\magisk_patched_boot_b_adb_insecure.img",
        type=Path,
        help="patched output image",
    )
    args = parser.parse_args()

    info = patch_boot(args.input, args.output)
    verify_output(args.output)

    print(f"input:  {args.input}")
    print(f"output: {args.output}")
    print(f"kernel_size={info.kernel_size}")
    print(f"ramdisk_size={info.ramdisk_size}")
    print(f"page_size={info.page_size}")
    print(f"ramdisk_offset={info.ramdisk_offset}")
    print(f"sha256: {sha256(args.output)}")
    print("verified: ro.adb.secure=0 and ro.debuggable=1")


if __name__ == "__main__":
    main()
